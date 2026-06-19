"""Tests for prediction endpoints."""

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
from src.models.prediction import Prediction
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


def _make_match(
    status: MatchStatus = MatchStatus.scheduled,
    kickoff_utc: datetime | None = None,
) -> Match:
    m = MagicMock(spec=Match)
    m.id = uuid.uuid4()
    m.match_number = 1
    m.stage = TournamentStage.group
    m.group_id = uuid.uuid4()
    m.home_team_id = None
    m.away_team_id = None
    m.home_team_placeholder = "Home"
    m.away_team_placeholder = "Away"
    m.kickoff_utc = kickoff_utc if kickoff_utc is not None else _now() + timedelta(hours=1)
    m.venue = "Stadium"
    m.status = status
    m.actual_home_score = None
    m.actual_away_score = None
    m.extra_time = False
    m.penalties = False
    m.postponed_reason = None
    m.deleted_at = None
    return m


def _make_prediction(
    player_id: uuid.UUID,
    match_id: uuid.UUID,
    update_count: int = 0,
    points_awarded: int | None = None,
    points_breakdown: dict | None = None,
) -> Prediction:
    p = MagicMock(spec=Prediction)
    p.id = uuid.uuid4()
    p.player_id = player_id
    p.match_id = match_id
    p.predicted_home = 2
    p.predicted_away = 1
    p.submitted_at = _now()
    p.update_count = update_count
    p.points_awarded = points_awarded
    p.points_breakdown = points_breakdown
    p.updated_at = _now()
    p.deleted_at = None
    return p


def _scalars(items: list) -> MagicMock:
    r = MagicMock()
    r.scalars.return_value.all.return_value = items
    return r


def _scalar_one(value: object) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
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


# ---------------------------------------------------------------------------
# PUT /api/v1/predictions/{match_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_prediction_create() -> None:
    """First-time submission creates a new prediction."""
    player = _make_player()
    match = _make_match(MatchStatus.scheduled)
    pred = _make_prediction(player.id, match.id)
    # Sequence: get match, get existing pred (None), refresh after add
    db = _stub_db([_scalar_one(match), _scalar_one(None)])
    db.refresh = AsyncMock(side_effect=lambda obj: _patch_pred(obj, pred))

    async with _override(db, player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                f"/api/v1/predictions/{match.id}",
                json={"predicted_home": 2, "predicted_away": 1},
                headers={"Authorization": "Bearer x"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["predicted_home"] == 2
    assert data["predicted_away"] == 1
    db.add.assert_called_once()


def _patch_pred(obj: object, template: Prediction) -> None:
    """Simulate refresh by copying fields from template onto obj."""
    for attr in (
        "id",
        "player_id",
        "match_id",
        "predicted_home",
        "predicted_away",
        "submitted_at",
        "update_count",
        "points_awarded",
        "points_breakdown",
        "updated_at",
        "deleted_at",
    ):
        setattr(obj, attr, getattr(template, attr))


@pytest.mark.asyncio
async def test_upsert_prediction_update_increments_count() -> None:
    """Updating an existing prediction increments update_count."""
    player = _make_player()
    match = _make_match(MatchStatus.scheduled)
    existing = _make_prediction(player.id, match.id, update_count=1)
    updated = _make_prediction(player.id, match.id, update_count=2)
    db = _stub_db([_scalar_one(match), _scalar_one(existing)])
    db.refresh = AsyncMock(side_effect=lambda obj: _patch_pred(obj, updated))

    async with _override(db, player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                f"/api/v1/predictions/{match.id}",
                json={"predicted_home": 3, "predicted_away": 0},
                headers={"Authorization": "Bearer x"},
            )

    assert resp.status_code == 200
    assert existing.update_count == 2
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_upsert_prediction_locked_match() -> None:
    """PUT on a non-scheduled match returns 409 PREDICTION_LOCKED."""
    player = _make_player()
    match = _make_match(MatchStatus.locked)
    db = _stub_db([_scalar_one(match)])

    async with _override(db, player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                f"/api/v1/predictions/{match.id}",
                json={"predicted_home": 1, "predicted_away": 1},
                headers={"Authorization": "Bearer x"},
            )

    assert resp.status_code == 409
    assert resp.json()["detail"] == "PREDICTION_LOCKED"


@pytest.mark.asyncio
async def test_upsert_prediction_completed_match_is_locked() -> None:
    """PUT on a completed match is also rejected."""
    player = _make_player()
    match = _make_match(MatchStatus.completed)
    db = _stub_db([_scalar_one(match)])

    async with _override(db, player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                f"/api/v1/predictions/{match.id}",
                json={"predicted_home": 0, "predicted_away": 0},
                headers={"Authorization": "Bearer x"},
            )

    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_upsert_prediction_race_window_returns_409() -> None:
    """Race window: status is still 'scheduled' but kickoff has passed → 409.

    The scheduler runs at intervals; between kickoff time and the next tick,
    a match may still have status=scheduled even though it shouldn't accept
    predictions. The PUT handler must refuse based on kickoff_utc directly.
    """
    player = _make_player()
    match = _make_match(
        status=MatchStatus.scheduled,
        kickoff_utc=_now() - timedelta(seconds=1),
    )
    db = _stub_db([_scalar_one(match)])

    async with _override(db, player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                f"/api/v1/predictions/{match.id}",
                json={"predicted_home": 2, "predicted_away": 1},
                headers={"Authorization": "Bearer x"},
            )

    assert resp.status_code == 409
    assert resp.json()["detail"] == "PREDICTION_LOCKED"
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_upsert_prediction_match_not_found() -> None:
    db = _stub_db([_scalar_one(None)])
    player = _make_player()

    async with _override(db, player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                f"/api/v1/predictions/{uuid.uuid4()}",
                json={"predicted_home": 1, "predicted_away": 0},
                headers={"Authorization": "Bearer x"},
            )

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/v1/predictions/me
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_my_predictions_returns_own() -> None:
    player = _make_player()
    pred = _make_prediction(player.id, uuid.uuid4())
    db = _stub_db([_scalars([pred])])

    async with _override(db, player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/predictions/me", headers={"Authorization": "Bearer x"})

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["player_id"] == str(player.id)


@pytest.mark.asyncio
async def test_my_predictions_empty() -> None:
    player = _make_player()
    db = _stub_db([_scalars([])])

    async with _override(db, player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/predictions/me", headers={"Authorization": "Bearer x"})

    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_my_predictions_breakdown_round_trips() -> None:
    """points_breakdown from a settled prediction is included in the response."""
    player = _make_player()
    breakdown = {"goals": 2, "result": 3, "exact": 5, "total": 10, "no_prediction": False}
    pred = _make_prediction(
        player.id,
        uuid.uuid4(),
        points_awarded=10,
        points_breakdown=breakdown,
    )
    db = _stub_db([_scalars([pred])])

    async with _override(db, player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/predictions/me", headers={"Authorization": "Bearer x"})

    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["points_awarded"] == 10
    assert data[0]["points_breakdown"] == breakdown


# ---------------------------------------------------------------------------
# GET /api/v1/predictions/match/{match_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_match_predictions_post_lock() -> None:
    player = _make_player()
    # A locked match has, by definition, already kicked off (the scheduler only
    # flips status→locked once kickoff_utc has passed). The shared reveal gate
    # keys on kickoff, so the fixture must reflect a past kickoff.
    match = _make_match(MatchStatus.locked, kickoff_utc=_now() - timedelta(minutes=5))
    pred = _make_prediction(player.id, match.id)
    profile = _make_player(player.id)
    db = _stub_db([_scalar_one(match), _rows([(pred, profile)])])

    with patch(
        "src.routers.predictions.shared_league_player_ids",
        return_value=frozenset({player.id}),
    ):
        async with _override(db, player):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    f"/api/v1/predictions/match/{match.id}",
                    headers={"Authorization": "Bearer x"},
                )

    assert resp.status_code == 200
    data = resp.json()
    assert data["match_id"] == str(match.id)
    assert len(data["predictions"]) == 1
    assert data["predictions"][0]["predicted_home"] == 2


@pytest.mark.asyncio
async def test_match_predictions_pre_lock_returns_403() -> None:
    player = _make_player()
    match = _make_match(MatchStatus.scheduled)
    db = _stub_db([_scalar_one(match)])

    async with _override(db, player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                f"/api/v1/predictions/match/{match.id}",
                headers={"Authorization": "Bearer x"},
            )

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_match_predictions_cancelled_returns_predictions() -> None:
    """Cancelled matches are post-lock — predictions should be visible."""
    player = _make_player()
    match = _make_match(MatchStatus.cancelled)
    pred = _make_prediction(player.id, match.id)
    profile = _make_player(player.id)
    db = _stub_db([_scalar_one(match), _rows([(pred, profile)])])

    with patch(
        "src.routers.predictions.shared_league_player_ids",
        return_value=frozenset({player.id}),
    ):
        async with _override(db, player):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    f"/api/v1/predictions/match/{match.id}",
                    headers={"Authorization": "Bearer x"},
                )

    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/v1/predictions/player/{player_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_player_predictions_only_post_lock() -> None:
    requester = _make_player()
    target_id = uuid.uuid4()
    target_profile = _make_player(target_id)
    pred = _make_prediction(target_id, uuid.uuid4())
    db = _stub_db([_scalar_one(target_profile), _scalars([pred])])

    with patch(
        "src.routers.predictions.shared_league_player_ids",
        return_value=frozenset({requester.id, target_id}),
    ):
        async with _override(db, requester):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    f"/api/v1/predictions/player/{target_id}",
                    headers={"Authorization": "Bearer x"},
                )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1


@pytest.mark.asyncio
async def test_player_predictions_player_not_found() -> None:
    requester = _make_player()
    db = _stub_db([_scalar_one(None)])

    async with _override(db, requester):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                f"/api/v1/predictions/player/{uuid.uuid4()}",
                headers={"Authorization": "Bearer x"},
            )

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_predictions_require_auth() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/predictions/me")
    assert resp.status_code in (401, 403)
