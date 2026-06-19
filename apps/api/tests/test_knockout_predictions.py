"""Tests for knockout prediction endpoints."""

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_player
from src.database import get_db
from src.main import app
from src.models.match import Match, MatchStatus
from src.models.prediction import KnockoutPrediction
from src.models.profile import PlayerRole, Profile
from src.models.team import TournamentStage

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _make_player(player_id: uuid.UUID | None = None) -> Profile:
    p = MagicMock(spec=Profile)
    p.avatar_url = None  # U23: prevent MagicMock default from failing Pydantic
    p.id = player_id or uuid.uuid4()
    p.display_name = "TestPlayer"
    p.role = PlayerRole.player
    p.deleted_at = None
    return p


HOME_TEAM_ID = uuid.uuid4()
AWAY_TEAM_ID = uuid.uuid4()


def _make_match(
    status: MatchStatus = MatchStatus.scheduled,
    stage: TournamentStage = TournamentStage.r32,
    home_team_id: uuid.UUID | None = None,
    away_team_id: uuid.UUID | None = None,
    kickoff_utc: datetime | None = None,
) -> Match:
    m = MagicMock(spec=Match)
    m.id = uuid.uuid4()
    m.match_number = 73
    m.stage = stage
    m.group_id = None
    m.home_team_id = home_team_id
    m.away_team_id = away_team_id
    m.home_team_placeholder = "1A"
    m.away_team_placeholder = "T1"
    m.kickoff_utc = kickoff_utc if kickoff_utc is not None else _now() + timedelta(hours=1)
    m.status = status
    m.actual_home_score = None
    m.actual_away_score = None
    m.deleted_at = None
    return m


def _make_ko_prediction(
    player_id: uuid.UUID,
    match_id: uuid.UUID,
    winner_id: uuid.UUID | None = None,
    update_count: int = 0,
) -> KnockoutPrediction:
    p = MagicMock(spec=KnockoutPrediction)
    p.id = uuid.uuid4()
    p.player_id = player_id
    p.match_id = match_id
    p.predicted_winner_id = winner_id or HOME_TEAM_ID
    p.submitted_at = _now()
    p.update_count = update_count
    p.points_awarded = None
    p.updated_at = _now()
    return p


def _scalar_one(value: object) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _scalars(items: list) -> MagicMock:
    r = MagicMock()
    r.scalars.return_value.all.return_value = items
    return r


def _rows(pairs: list[tuple]) -> MagicMock:
    r = MagicMock()
    r.all.return_value = pairs
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


def _patch_pred(obj: object, template: KnockoutPrediction) -> None:
    for attr in (
        "id",
        "player_id",
        "match_id",
        "predicted_winner_id",
        "submitted_at",
        "update_count",
        "points_awarded",
        "updated_at",
    ):
        setattr(obj, attr, getattr(template, attr))


# ---------------------------------------------------------------------------
# PUT /api/v1/knockout-predictions/{match_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_knockout_prediction_create() -> None:
    """First submission creates a new knockout prediction."""
    player = _make_player()
    match = _make_match()
    pred = _make_ko_prediction(player.id, match.id, HOME_TEAM_ID)
    # Sequence: get match, get existing pred (None), refresh. No round-lock query
    # any more — the per-match kickoff lock is the only gate (U22.1).
    db = _stub_db([_scalar_one(match), _scalar_one(None)])
    db.refresh = AsyncMock(side_effect=lambda obj: _patch_pred(obj, pred))

    async with _override(db, player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                f"/api/v1/knockout-predictions/{match.id}",
                json={"predicted_winner_id": str(HOME_TEAM_ID)},
                headers={"Authorization": "Bearer x"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["predicted_winner_id"] == str(HOME_TEAM_ID)
    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_upsert_knockout_prediction_update() -> None:
    """Updating an existing prediction increments update_count."""
    player = _make_player()
    match = _make_match()
    existing = _make_ko_prediction(player.id, match.id, HOME_TEAM_ID, update_count=1)
    updated = _make_ko_prediction(player.id, match.id, AWAY_TEAM_ID, update_count=2)
    db = _stub_db([_scalar_one(match), _scalar_one(existing)])
    db.refresh = AsyncMock(side_effect=lambda obj: _patch_pred(obj, updated))

    async with _override(db, player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                f"/api/v1/knockout-predictions/{match.id}",
                json={"predicted_winner_id": str(AWAY_TEAM_ID)},
                headers={"Authorization": "Bearer x"},
            )

    assert resp.status_code == 200
    assert existing.update_count == 2
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_upsert_knockout_prediction_sibling_started_does_not_lock() -> None:
    """U22.1 per-match lock: a sibling tie in the same stage having kicked off no
    longer locks this match. With this match's own kickoff still in the future the
    upsert succeeds — the handler issues no round-level query at all (proven by the
    stub providing only match + existing-pred lookups, no sibling-scan result)."""
    player = _make_player()
    match = _make_match(
        status=MatchStatus.scheduled,
        kickoff_utc=_now() + timedelta(hours=2),
    )
    pred = _make_ko_prediction(player.id, match.id, HOME_TEAM_ID)
    db = _stub_db([_scalar_one(match), _scalar_one(None)])
    db.refresh = AsyncMock(side_effect=lambda obj: _patch_pred(obj, pred))

    async with _override(db, player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                f"/api/v1/knockout-predictions/{match.id}",
                json={"predicted_winner_id": str(HOME_TEAM_ID)},
                headers={"Authorization": "Bearer x"},
            )

    assert resp.status_code == 200
    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_upsert_knockout_prediction_race_window_returns_409() -> None:
    """Race window: status still 'scheduled', kickoff already passed → 409.

    The per-match kickoff lock refuses the write even if the scheduler hasn't
    yet flipped the match's status away from 'scheduled' (U22.1).
    """
    player = _make_player()
    match = _make_match(
        status=MatchStatus.scheduled,
        kickoff_utc=_now() - timedelta(seconds=1),
    )
    # Only the initial match lookup runs; kickoff check short-circuits.
    db = _stub_db([_scalar_one(match)])

    async with _override(db, player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                f"/api/v1/knockout-predictions/{match.id}",
                json={"predicted_winner_id": str(HOME_TEAM_ID)},
                headers={"Authorization": "Bearer x"},
            )

    assert resp.status_code == 409
    assert resp.json()["detail"] == "PREDICTION_LOCKED"
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_upsert_knockout_prediction_match_not_found() -> None:
    db = _stub_db([_scalar_one(None)])
    player = _make_player()

    async with _override(db, player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                f"/api/v1/knockout-predictions/{uuid.uuid4()}",
                json={"predicted_winner_id": str(HOME_TEAM_ID)},
                headers={"Authorization": "Bearer x"},
            )

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_upsert_knockout_prediction_invalid_winner() -> None:
    """Returns 422 when predicted_winner_id is not home or away team (when both are known)."""
    player = _make_player()
    match = _make_match(home_team_id=HOME_TEAM_ID, away_team_id=AWAY_TEAM_ID)
    db = _stub_db([_scalar_one(match)])
    other_team = uuid.uuid4()

    async with _override(db, player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                f"/api/v1/knockout-predictions/{match.id}",
                json={"predicted_winner_id": str(other_team)},
                headers={"Authorization": "Bearer x"},
            )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_upsert_knockout_prediction_no_team_validation_when_unknown() -> None:
    """When match teams are not yet set, any valid team UUID is accepted."""
    player = _make_player()
    # Match with no team IDs (placeholder stage)
    match = _make_match(home_team_id=None, away_team_id=None)
    any_team = uuid.uuid4()
    pred = _make_ko_prediction(player.id, match.id, any_team)
    db = _stub_db([_scalar_one(match), _scalar_one(None)])
    db.refresh = AsyncMock(side_effect=lambda obj: _patch_pred(obj, pred))

    async with _override(db, player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                f"/api/v1/knockout-predictions/{match.id}",
                json={"predicted_winner_id": str(any_team)},
                headers={"Authorization": "Bearer x"},
            )

    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/v1/knockout-predictions/me
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_my_knockout_predictions_returns_own() -> None:
    player = _make_player()
    pred = _make_ko_prediction(player.id, uuid.uuid4())
    db = _stub_db([_scalars([pred])])

    async with _override(db, player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/knockout-predictions/me",
                headers={"Authorization": "Bearer x"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["player_id"] == str(player.id)


@pytest.mark.asyncio
async def test_my_knockout_predictions_empty() -> None:
    player = _make_player()
    db = _stub_db([_scalars([])])

    async with _override(db, player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/knockout-predictions/me",
                headers={"Authorization": "Bearer x"},
            )

    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# GET /api/v1/knockout-predictions/match/{match_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_match_knockout_predictions_post_lock() -> None:
    player = _make_player()
    # Kickoff in the past → the match has locked, so predictions are revealed.
    match = _make_match(status=MatchStatus.locked, kickoff_utc=_now() - timedelta(hours=1))
    pred = _make_ko_prediction(player.id, match.id)
    profile = _make_player(player.id)
    db = _stub_db([_scalar_one(match), _rows([(pred, profile)])])

    with patch(
        "src.routers.knockout_predictions.shared_league_player_ids",
        return_value=frozenset({player.id}),
    ):
        async with _override(db, player):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    f"/api/v1/knockout-predictions/match/{match.id}",
                    headers={"Authorization": "Bearer x"},
                )

    assert resp.status_code == 200
    data = resp.json()
    assert data["match_id"] == str(match.id)
    assert len(data["predictions"]) == 1
    assert data["predictions"][0]["player_name"] == "TestPlayer"


@pytest.mark.asyncio
async def test_match_knockout_predictions_pre_lock_returns_403() -> None:
    """Kickoff still in the future → predictions hidden (per-match reveal gate)."""
    player = _make_player()
    match = _make_match(status=MatchStatus.scheduled, kickoff_utc=_now() + timedelta(hours=1))
    db = _stub_db([_scalar_one(match)])

    async with _override(db, player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                f"/api/v1/knockout-predictions/match/{match.id}",
                headers={"Authorization": "Bearer x"},
            )

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_match_knockout_predictions_kickoff_passed_while_scheduled_visible() -> None:
    """U22.1 per-match reveal: a match whose kickoff has passed reveals predictions
    even if its status is still 'scheduled' (scheduler lag). The old gate keyed on
    status would have kept this 403 — proving the switch to a kickoff-based gate."""
    player = _make_player()
    match = _make_match(status=MatchStatus.scheduled, kickoff_utc=_now() - timedelta(seconds=1))
    pred = _make_ko_prediction(player.id, match.id)
    profile = _make_player(player.id)
    db = _stub_db([_scalar_one(match), _rows([(pred, profile)])])

    with patch(
        "src.routers.knockout_predictions.shared_league_player_ids",
        return_value=frozenset({player.id}),
    ):
        async with _override(db, player):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    f"/api/v1/knockout-predictions/match/{match.id}",
                    headers={"Authorization": "Bearer x"},
                )

    assert resp.status_code == 200
    assert len(resp.json()["predictions"]) == 1


@pytest.mark.asyncio
async def test_match_knockout_predictions_completed_visible() -> None:
    """Completed matches show predictions (kickoff is in the past)."""
    player = _make_player()
    match = _make_match(status=MatchStatus.completed, kickoff_utc=_now() - timedelta(hours=2))
    pred = _make_ko_prediction(player.id, match.id)
    profile = _make_player(player.id)
    db = _stub_db([_scalar_one(match), _rows([(pred, profile)])])

    with patch(
        "src.routers.knockout_predictions.shared_league_player_ids",
        return_value=frozenset({player.id}),
    ):
        async with _override(db, player):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    f"/api/v1/knockout-predictions/match/{match.id}",
                    headers={"Authorization": "Bearer x"},
                )

    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_knockout_predictions_require_auth() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/knockout-predictions/me")
    assert resp.status_code in (401, 403)
