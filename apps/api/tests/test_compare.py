"""Tests for Phase 9.3 head-to-head compare endpoint."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from src.database import get_db
from src.main import app
from src.models.match import Match
from src.models.prediction import KnockoutPrediction, Prediction
from src.models.profile import Profile

# Bound to the original function at import time, so the autouse no-op patch
# (which reassigns the module attribute) does not shadow it in these unit tests.
from src.routers.compare import _require_league_members
from src.routers.leagues import require_league_member

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SLUG = "test-league"
PLAYER_A_ID = uuid.uuid4()
PLAYER_B_ID = uuid.uuid4()
MATCH_1_ID = uuid.uuid4()
MATCH_2_ID = uuid.uuid4()


def _league() -> MagicMock:
    league = MagicMock()
    league.id = uuid.uuid4()
    return league


@pytest.fixture(autouse=True)
def _skip_member_check() -> Iterator[None]:
    """Per-league compare verifies membership separately; the unit tests mock
    only the comparison query order, so no-op the membership guard here."""
    with patch(
        "src.routers.compare._require_league_members",
        new=AsyncMock(return_value=None),
    ):
        yield


def _profile(pid: uuid.UUID, name: str) -> MagicMock:
    p = MagicMock(spec=Profile)
    p.avatar_url = None  # U23: prevent MagicMock default from failing Pydantic
    p.id = pid
    p.display_name = name
    p.deleted_at = None
    return p


def _match(
    mid: uuid.UUID,
    *,
    kickoff: datetime | None = None,
    stage: str = "group",
    actual_home: int | None = 2,
    actual_away: int | None = 1,
) -> MagicMock:
    m = MagicMock(spec=Match)
    m.id = mid
    m.kickoff_utc = kickoff or datetime(2026, 6, 14, 18, 0, 0)
    m.stage = MagicMock()
    m.stage.value = stage
    m.actual_home_score = actual_home
    m.actual_away_score = actual_away
    m.home_team_id = None
    m.away_team_id = None
    m.home_team_placeholder = "Team A"
    m.away_team_placeholder = "Team B"
    m.deleted_at = None
    return m


def _prediction(
    player_id: uuid.UUID,
    match: MagicMock,
    *,
    predicted_home: int = 2,
    predicted_away: int = 1,
    points: int = 10,
) -> MagicMock:
    p = MagicMock(spec=Prediction)
    p.player_id = player_id
    p.match_id = match.id
    p.predicted_home = predicted_home
    p.predicted_away = predicted_away
    p.points_awarded = points
    p.deleted_at = None
    return p


def _ko_prediction(
    player_id: uuid.UUID,
    match: MagicMock,
    *,
    points: int = 10,
) -> MagicMock:
    p = MagicMock(spec=KnockoutPrediction)
    p.player_id = player_id
    p.match_id = match.id
    p.points_awarded = points
    return p


def _requester() -> MagicMock:
    r = MagicMock(spec=Profile)
    r.avatar_url = None  # U23: prevent MagicMock default from failing Pydantic
    r.id = uuid.uuid4()
    return r


def _db_with(mock_db: AsyncMock):  # type: ignore[no-untyped-def]
    async def _override():  # type: ignore[no-untyped-def]
        yield mock_db

    return _override


def _build_mock_db(
    profile_a: MagicMock | None,
    profile_b: MagicMock | None,
    group_rows: list[tuple[MagicMock, MagicMock]],
    ko_rows: list[tuple[MagicMock, MagicMock]],
) -> AsyncMock:
    """Build a mock DB that returns the given data in query order."""
    mock_db = AsyncMock()
    call_count = 0

    async def side_effect(stmt: object) -> MagicMock:
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = profile_a
        elif call_count == 2:
            result.scalar_one_or_none.return_value = profile_b
        elif call_count == 3:
            # Group predictions
            result.all.return_value = group_rows
        elif call_count == 4:
            # Knockout predictions
            result.all.return_value = ko_rows
        else:
            # Teams batch fetch
            result.scalars.return_value.all.return_value = []
        return result

    mock_db.execute = AsyncMock(side_effect=side_effect)
    return mock_db


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compare_returns_correct_winner_summary() -> None:
    match1 = _match(MATCH_1_ID)
    match2 = _match(MATCH_2_ID, kickoff=datetime(2026, 6, 15, 18, 0, 0))

    pred_a1 = _prediction(PLAYER_A_ID, match1, points=10)  # A wins this match
    pred_b1 = _prediction(PLAYER_B_ID, match1, points=3)
    pred_a2 = _prediction(PLAYER_A_ID, match2, points=0)  # B wins this match
    pred_b2 = _prediction(PLAYER_B_ID, match2, points=5)

    group_rows = [(pred_a1, match1), (pred_b1, match1), (pred_a2, match2), (pred_b2, match2)]
    mock_db = _build_mock_db(
        _profile(PLAYER_A_ID, "Alice"), _profile(PLAYER_B_ID, "Bob"), group_rows, []
    )

    app.dependency_overrides[require_league_member] = lambda: (_requester(), _league())
    app.dependency_overrides[get_db] = _db_with(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/leagues/{SLUG}/compare/{PLAYER_A_ID}/{PLAYER_B_ID}")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["player_a"]["name"] == "Alice"
    assert body["player_b"]["name"] == "Bob"
    assert body["summary"]["player_a_wins"] == 1
    assert body["summary"]["player_b_wins"] == 1
    assert body["summary"]["draws"] == 0
    assert len(body["matches"]) == 2


@pytest.mark.asyncio
async def test_compare_draw_when_equal_points() -> None:
    match1 = _match(MATCH_1_ID)
    pred_a = _prediction(PLAYER_A_ID, match1, points=5)
    pred_b = _prediction(PLAYER_B_ID, match1, points=5)
    mock_db = _build_mock_db(
        _profile(PLAYER_A_ID, "Alice"),
        _profile(PLAYER_B_ID, "Bob"),
        [(pred_a, match1), (pred_b, match1)],
        [],
    )

    app.dependency_overrides[require_league_member] = lambda: (_requester(), _league())
    app.dependency_overrides[get_db] = _db_with(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/leagues/{SLUG}/compare/{PLAYER_A_ID}/{PLAYER_B_ID}")
    finally:
        app.dependency_overrides.clear()

    body = resp.json()
    assert body["summary"]["draws"] == 1
    assert body["matches"][0]["winner"] == "draw"


@pytest.mark.asyncio
async def test_compare_edge_case_one_player_missing_prediction() -> None:
    """Player B has no prediction for a match — treated as 0 pts, A wins."""
    match1 = _match(MATCH_1_ID)
    pred_a = _prediction(PLAYER_A_ID, match1, points=8)
    # Player B has no prediction for match1
    mock_db = _build_mock_db(
        _profile(PLAYER_A_ID, "Alice"),
        _profile(PLAYER_B_ID, "Bob"),
        [(pred_a, match1)],
        [],
    )

    app.dependency_overrides[require_league_member] = lambda: (_requester(), _league())
    app.dependency_overrides[get_db] = _db_with(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/leagues/{SLUG}/compare/{PLAYER_A_ID}/{PLAYER_B_ID}")
    finally:
        app.dependency_overrides.clear()

    body = resp.json()
    assert body["summary"]["player_a_wins"] == 1
    assert body["matches"][0]["player_b_points"] == 0
    assert body["matches"][0]["player_b_predicted_home"] is None
    assert body["matches"][0]["winner"] == "a"


@pytest.mark.asyncio
async def test_compare_includes_knockout_predictions() -> None:
    ko_match = _match(MATCH_1_ID, stage="r16")
    ko_a = _ko_prediction(PLAYER_A_ID, ko_match, points=15)
    ko_b = _ko_prediction(PLAYER_B_ID, ko_match, points=0)
    mock_db = _build_mock_db(
        _profile(PLAYER_A_ID, "Alice"),
        _profile(PLAYER_B_ID, "Bob"),
        [],
        [(ko_a, ko_match), (ko_b, ko_match)],
    )

    app.dependency_overrides[require_league_member] = lambda: (_requester(), _league())
    app.dependency_overrides[get_db] = _db_with(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/leagues/{SLUG}/compare/{PLAYER_A_ID}/{PLAYER_B_ID}")
    finally:
        app.dependency_overrides.clear()

    body = resp.json()
    assert len(body["matches"]) == 1
    assert body["matches"][0]["stage"] == "r16"
    assert body["matches"][0]["player_a_points"] == 15
    assert body["matches"][0]["player_a_predicted_home"] is None  # knockout has no score


@pytest.mark.asyncio
async def test_compare_empty_when_no_settled_predictions() -> None:
    mock_db = _build_mock_db(
        _profile(PLAYER_A_ID, "Alice"),
        _profile(PLAYER_B_ID, "Bob"),
        [],
        [],
    )

    app.dependency_overrides[require_league_member] = lambda: (_requester(), _league())
    app.dependency_overrides[get_db] = _db_with(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/leagues/{SLUG}/compare/{PLAYER_A_ID}/{PLAYER_B_ID}")
    finally:
        app.dependency_overrides.clear()

    body = resp.json()
    assert body["summary"]["player_a_wins"] == 0
    assert body["summary"]["player_b_wins"] == 0
    assert body["summary"]["draws"] == 0
    assert body["matches"] == []


@pytest.mark.asyncio
async def test_compare_404_unknown_player_a() -> None:
    mock_db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=result)

    app.dependency_overrides[require_league_member] = lambda: (_requester(), _league())
    app.dependency_overrides[get_db] = _db_with(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/leagues/{SLUG}/compare/{uuid.uuid4()}/{uuid.uuid4()}")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_compare_404_unknown_player_b() -> None:
    call_count = 0

    async def side_effect(stmt: object) -> MagicMock:
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = _profile(PLAYER_A_ID, "Alice")
        else:
            result.scalar_one_or_none.return_value = None
        return result

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=side_effect)

    app.dependency_overrides[require_league_member] = lambda: (_requester(), _league())
    app.dependency_overrides[get_db] = _db_with(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/leagues/{SLUG}/compare/{PLAYER_A_ID}/{uuid.uuid4()}")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_compare_requires_auth() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/v1/leagues/{SLUG}/compare/{uuid.uuid4()}/{uuid.uuid4()}")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_compare_matches_sorted_by_kickoff() -> None:
    """Matches should appear in chronological kickoff order."""
    match_early = _match(MATCH_1_ID, kickoff=datetime(2026, 6, 10))
    match_late = _match(MATCH_2_ID, kickoff=datetime(2026, 6, 20))

    pred_a_late = _prediction(PLAYER_A_ID, match_late, points=5)
    pred_a_early = _prediction(PLAYER_A_ID, match_early, points=3)

    # Rows come in reversed order
    group_rows = [(pred_a_late, match_late), (pred_a_early, match_early)]
    mock_db = _build_mock_db(
        _profile(PLAYER_A_ID, "Alice"),
        _profile(PLAYER_B_ID, "Bob"),
        group_rows,
        [],
    )

    app.dependency_overrides[require_league_member] = lambda: (_requester(), _league())
    app.dependency_overrides[get_db] = _db_with(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/leagues/{SLUG}/compare/{PLAYER_A_ID}/{PLAYER_B_ID}")
    finally:
        app.dependency_overrides.clear()

    body = resp.json()
    assert body["matches"][0]["player_a_points"] == 3  # early match first
    assert body["matches"][1]["player_a_points"] == 5  # late match second


# ---------------------------------------------------------------------------
# Per-league membership guard
# ---------------------------------------------------------------------------


def _members_db(member_ids: list[uuid.UUID]) -> AsyncMock:
    mock_db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = member_ids
    mock_db.execute = AsyncMock(return_value=result)
    return mock_db


@pytest.mark.asyncio
async def test_require_league_members_passes_when_both_members() -> None:
    league_id = uuid.uuid4()
    await _require_league_members(
        league_id, [PLAYER_A_ID, PLAYER_B_ID], _members_db([PLAYER_A_ID, PLAYER_B_ID])
    )


@pytest.mark.asyncio
async def test_require_league_members_404_when_one_is_not_a_member() -> None:
    league_id = uuid.uuid4()
    # Only player A is in the league; B is a member of some other league.
    with pytest.raises(HTTPException) as exc:
        await _require_league_members(
            league_id, [PLAYER_A_ID, PLAYER_B_ID], _members_db([PLAYER_A_ID])
        )
    assert exc.value.status_code == 404
