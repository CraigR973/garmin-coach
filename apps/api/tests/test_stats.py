"""Tests for Phase 9.1 stats endpoints and computation logic."""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.auth import get_current_player
from src.database import get_db
from src.main import app
from src.models.profile import Profile
from src.routers.leagues import require_league_member
from src.services.stats import PlayerStatsData, _compute_stats, _PredRow

SLUG = "test-league"


def _league() -> MagicMock:
    league = MagicMock()
    league.id = uuid.uuid4()
    return league


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _player(display_name: str = "Alice") -> MagicMock:
    p = MagicMock(spec=Profile)
    p.id = uuid.uuid4()
    p.display_name = display_name
    p.is_active = True
    p.deleted_at = None
    p.avatar_url = None  # U23: prevent MagicMock default from failing Pydantic
    return p


def _db_with(mock_db: AsyncMock):  # type: ignore[no-untyped-def]
    async def _override():  # type: ignore[no-untyped-def]
        yield mock_db

    return _override


def _pred_row(
    *,
    player_id: uuid.UUID | None = None,
    points_awarded: int = 5,
    result_pts: int = 3,
    exact_pts: int = 0,
    no_prediction: bool = False,
    submitted_at: datetime | None = None,
    kickoff_utc: datetime | None = None,
    stage: str = "group",
) -> _PredRow:
    breakdown = {
        "result": result_pts,
        "exact": exact_pts,
        "goals": max(0, points_awarded - result_pts - exact_pts),
        "total": points_awarded,
        "no_prediction": no_prediction,
    }
    return _PredRow(
        player_id=player_id or uuid.uuid4(),
        points_awarded=0 if no_prediction else points_awarded,
        points_breakdown=breakdown,
        submitted_at=submitted_at,
        kickoff_utc=kickoff_utc,
        stage=stage,
    )


def _ko_row(
    *,
    player_id: uuid.UUID | None = None,
    points_awarded: int = 10,
    kickoff_utc: datetime | None = None,
    stage: str = "r16",
) -> _PredRow:
    return _PredRow(
        player_id=player_id or uuid.uuid4(),
        points_awarded=points_awarded,
        points_breakdown=None,
        submitted_at=None,
        kickoff_utc=kickoff_utc,
        stage=stage,
    )


# ---------------------------------------------------------------------------
# Unit tests for _compute_stats
# ---------------------------------------------------------------------------


def test_compute_stats_empty() -> None:
    pid = uuid.uuid4()
    stats = _compute_stats(pid, "Alice", [], [])
    assert stats.total_predictions_settled == 0
    assert stats.accuracy_pct == 0.0
    assert stats.exact_rate_pct == 0.0
    assert stats.avg_pts_per_prediction == 0.0
    assert stats.total_points == 0
    assert stats.best_round is None
    assert stats.worst_round is None
    assert stats.current_streak == 0
    assert stats.avg_prediction_timing_mins is None


def test_compute_stats_accuracy() -> None:
    pid = uuid.uuid4()
    rows = [
        _pred_row(player_id=pid, points_awarded=8, result_pts=3, exact_pts=5),  # correct + exact
        _pred_row(player_id=pid, points_awarded=3, result_pts=3, exact_pts=0),  # correct outcome
        _pred_row(player_id=pid, points_awarded=0, result_pts=0, exact_pts=0),  # wrong
    ]
    stats = _compute_stats(pid, "Alice", rows, [])
    assert stats.accuracy_pct == round(2 / 3 * 100, 1)
    assert stats.exact_rate_pct == round(1 / 3 * 100, 1)
    assert stats.total_points == 11
    assert stats.total_predictions_settled == 3


def test_compute_stats_excludes_no_prediction_from_accuracy() -> None:
    pid = uuid.uuid4()
    rows = [
        _pred_row(player_id=pid, points_awarded=3, result_pts=3),
        _pred_row(player_id=pid, no_prediction=True),  # should not count toward denominator
    ]
    stats = _compute_stats(pid, "Alice", rows, [])
    # accuracy = 1/1 = 100%, not 1/2
    assert stats.accuracy_pct == 100.0
    # total settled includes the no_prediction row (it still happened)
    assert stats.total_predictions_settled == 2


def test_compute_stats_current_streak() -> None:
    pid = uuid.uuid4()
    t1 = datetime(2026, 6, 10)
    t2 = datetime(2026, 6, 11)
    t3 = datetime(2026, 6, 12)
    t4 = datetime(2026, 6, 13)
    rows = [
        _pred_row(player_id=pid, points_awarded=5, kickoff_utc=t1),
        _pred_row(player_id=pid, points_awarded=0, kickoff_utc=t2),  # streak breaker
        _pred_row(player_id=pid, points_awarded=3, kickoff_utc=t3),
        _pred_row(player_id=pid, points_awarded=7, kickoff_utc=t4),  # most recent
    ]
    stats = _compute_stats(pid, "Alice", rows, [])
    assert stats.current_streak == 2


def test_compute_stats_streak_all_scoring() -> None:
    pid = uuid.uuid4()
    rows = [
        _pred_row(player_id=pid, points_awarded=5, kickoff_utc=datetime(2026, 6, 10)),
        _pred_row(player_id=pid, points_awarded=3, kickoff_utc=datetime(2026, 6, 11)),
    ]
    stats = _compute_stats(pid, "Alice", rows, [])
    assert stats.current_streak == 2


def test_compute_stats_best_worst_round() -> None:
    pid = uuid.uuid4()
    group_rows = [
        _pred_row(player_id=pid, points_awarded=10, stage="group"),
        _pred_row(player_id=pid, points_awarded=5, stage="group"),
    ]
    ko_rows = [
        _ko_row(player_id=pid, points_awarded=0, stage="r16"),
    ]
    stats = _compute_stats(pid, "Alice", group_rows, ko_rows)
    assert stats.best_round == "group"
    assert stats.best_round_points == 15
    assert stats.worst_round == "r16"
    assert stats.worst_round_points == 0


def test_compute_stats_prediction_timing() -> None:
    pid = uuid.uuid4()
    kickoff = datetime(2026, 6, 15, 18, 0, 0)
    submitted = datetime(2026, 6, 15, 12, 0, 0)  # 6 hours = 360 mins before
    rows = [
        _pred_row(player_id=pid, submitted_at=submitted, kickoff_utc=kickoff),
    ]
    stats = _compute_stats(pid, "Alice", rows, [])
    assert stats.avg_prediction_timing_mins == 360.0


def test_compute_stats_ignores_negative_timing() -> None:
    """Submissions after kickoff should not count in timing average."""
    pid = uuid.uuid4()
    kickoff = datetime(2026, 6, 15, 18, 0, 0)
    late = datetime(2026, 6, 15, 19, 0, 0)  # after kickoff
    early = datetime(2026, 6, 15, 16, 0, 0)  # 2h before = 120 mins
    rows = [
        _pred_row(player_id=pid, submitted_at=late, kickoff_utc=kickoff),
        _pred_row(player_id=pid, submitted_at=early, kickoff_utc=kickoff),
    ]
    stats = _compute_stats(pid, "Alice", rows, [])
    assert stats.avg_prediction_timing_mins == 120.0


def test_compute_stats_includes_knockout_in_totals() -> None:
    pid = uuid.uuid4()
    group = [_pred_row(player_id=pid, points_awarded=5)]
    ko = [_ko_row(player_id=pid, points_awarded=10)]
    stats = _compute_stats(pid, "Alice", group, ko)
    assert stats.total_predictions_settled == 2
    assert stats.total_points == 15
    assert round(stats.avg_pts_per_prediction, 2) == 7.5


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_my_stats_returns_200() -> None:
    player = _player("Alice")
    mock_db = AsyncMock()
    stats_data = PlayerStatsData(
        player_id=str(player.id),
        player_name="Alice",
        total_predictions_settled=10,
        accuracy_pct=70.0,
        exact_rate_pct=20.0,
        avg_pts_per_prediction=4.5,
        total_points=45,
        best_round="group",
        best_round_points=30,
        worst_round="r16",
        worst_round_points=0,
        current_streak=3,
        avg_prediction_timing_mins=120.0,
    )

    with patch("src.routers.stats.get_player_stats", return_value=stats_data):
        app.dependency_overrides[get_current_player] = lambda: player
        app.dependency_overrides[get_db] = _db_with(mock_db)
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/v1/stats/me")
        finally:
            app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["player_id"] == str(player.id)
    assert body["accuracy_pct"] == 70.0
    assert body["current_streak"] == 3
    assert body["best_round"] == "group"


@pytest.mark.asyncio
async def test_get_stats_by_player_id_404() -> None:
    requester = _player("Bob")
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_result)

    app.dependency_overrides[get_current_player] = lambda: requester
    app.dependency_overrides[get_db] = _db_with(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/stats/{uuid.uuid4()}")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_stats_by_player_id_returns_stats() -> None:
    requester = _player("Bob")
    target = _player("Alice")
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = target
    mock_db.execute = AsyncMock(return_value=mock_result)

    stats_data = PlayerStatsData(
        player_id=str(target.id),
        player_name="Alice",
        total_predictions_settled=5,
        accuracy_pct=80.0,
        exact_rate_pct=40.0,
        avg_pts_per_prediction=6.0,
        total_points=30,
        best_round="group",
        best_round_points=20,
        worst_round="r16",
        worst_round_points=10,
        current_streak=1,
        avg_prediction_timing_mins=240.0,
    )

    with (
        patch("src.routers.stats.get_player_stats", return_value=stats_data),
        patch(
            "src.routers.stats.shared_league_player_ids",
            return_value=frozenset({requester.id, target.id}),
        ),
    ):
        app.dependency_overrides[get_current_player] = lambda: requester
        app.dependency_overrides[get_db] = _db_with(mock_db)
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(f"/api/v1/stats/{target.id}")
        finally:
            app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["player_name"] == "Alice"
    assert body["accuracy_pct"] == 80.0


@pytest.mark.asyncio
async def test_get_league_stats_returns_list() -> None:
    # Endpoint first loads member ids, then delegates to get_league_stats.
    mock_db = AsyncMock()
    member_result = MagicMock()
    member_result.scalars.return_value.all.return_value = [uuid.uuid4()]
    mock_db.execute = AsyncMock(return_value=member_result)
    stats_list = [
        PlayerStatsData(
            player_id=str(uuid.uuid4()),
            player_name="Alice",
            total_predictions_settled=10,
            accuracy_pct=60.0,
            exact_rate_pct=10.0,
            avg_pts_per_prediction=3.5,
            total_points=35,
            best_round="group",
            best_round_points=25,
            worst_round="r16",
            worst_round_points=10,
            current_streak=0,
            avg_prediction_timing_mins=None,
        )
    ]

    with patch("src.routers.stats.get_league_stats", return_value=stats_list):
        app.dependency_overrides[require_league_member] = lambda: (_player("Bob"), _league())
        app.dependency_overrides[get_db] = _db_with(mock_db)
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(f"/api/v1/leagues/{SLUG}/stats")
        finally:
            app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["player_name"] == "Alice"
    assert body[0]["avg_prediction_timing_mins"] is None


@pytest.mark.asyncio
async def test_stats_requires_auth() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/stats/me")
    assert resp.status_code == 401
