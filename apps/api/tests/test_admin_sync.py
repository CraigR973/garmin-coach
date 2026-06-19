"""Tests for Phase 5.4 admin sync endpoints (GET /sync/status, POST /sync/trigger, GET /results)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import require_admin
from src.database import get_db
from src.main import app
from src.models.match import Match, MatchStatus, ResultSource
from src.models.notification import ActionType, ActorType, AuditLog
from src.models.profile import PlayerRole, Profile
from src.models.team import TournamentStage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _make_admin() -> Profile:
    p = MagicMock(spec=Profile)
    p.avatar_url = None  # U23: prevent MagicMock default from failing Pydantic
    p.id = uuid.uuid4()
    p.display_name = "Admin"
    p.role = PlayerRole.admin
    p.timezone = "UTC"
    p.deleted_at = None
    return p


def _make_audit(action: ActionType, ts: datetime | None = None) -> MagicMock:
    a = MagicMock(spec=AuditLog)
    a.id = uuid.uuid4()
    a.actor_type = ActorType.system
    a.action_type = action
    a.timestamp = ts or _now()
    a.changes = {"detail": "test error"}
    return a


def _make_match(
    *,
    result_source: ResultSource | None = ResultSource.auto,
    home_score: int | None = 2,
    away_score: int | None = 1,
) -> MagicMock:
    m = MagicMock(spec=Match)
    m.id = uuid.uuid4()
    m.match_number = 1
    m.status = MatchStatus.completed
    m.stage = TournamentStage.group
    m.result_source = result_source
    m.actual_home_score = home_score
    m.actual_away_score = away_score
    m.extra_time = False
    m.penalties = False
    m.kickoff_utc = _now()
    m.result_entered_at = _now()
    m.home_team_id = None
    m.away_team_id = None
    m.home_team_placeholder = "Home"
    m.away_team_placeholder = "Away"
    m.deleted_at = None
    return m


def _build_mock_scheduler(next_run_at: datetime | None = None) -> MagicMock:
    scheduler = MagicMock()
    job = MagicMock()
    job.next_run_time = next_run_at
    scheduler.get_job.return_value = job
    return scheduler


# ---------------------------------------------------------------------------
# GET /api/v1/admin/sync/status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_status_no_history() -> None:
    """Returns nulls when no audit rows exist."""
    admin = _make_admin()
    mock_db = AsyncMock(spec=AsyncSession)

    empty_result = MagicMock()
    empty_result.scalar_one_or_none.return_value = None
    errors_result = MagicMock()
    errors_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(side_effect=[empty_result, errors_result])

    async def _db_override() -> AsyncGenerator[AsyncMock, None]:
        yield mock_db

    app.dependency_overrides[get_db] = _db_override
    app.dependency_overrides[require_admin] = lambda: admin
    app.state.scheduler = _build_mock_scheduler()

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/admin/sync/status")
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(require_admin, None)

    assert resp.status_code == 200
    data = resp.json()
    assert data["last_sync_at"] is None
    assert data["last_sync_action"] is None
    assert data["recent_errors"] == []


@pytest.mark.asyncio
async def test_sync_status_with_successful_run() -> None:
    """last_sync_at and last_sync_action populated from latest audit row."""
    admin = _make_admin()
    mock_db = AsyncMock(spec=AsyncSession)

    ts = datetime(2026, 6, 14, 12, 0, 0)
    audit = _make_audit(ActionType.result_auto_fetched, ts)

    last_result = MagicMock()
    last_result.scalar_one_or_none.return_value = audit
    errors_result = MagicMock()
    errors_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(side_effect=[last_result, errors_result])

    async def _db_override() -> AsyncGenerator[AsyncMock, None]:
        yield mock_db

    app.dependency_overrides[get_db] = _db_override
    app.dependency_overrides[require_admin] = lambda: admin
    app.state.scheduler = _build_mock_scheduler(datetime(2026, 6, 14, 12, 5, 0))

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/admin/sync/status")
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(require_admin, None)

    assert resp.status_code == 200
    data = resp.json()
    assert data["last_sync_action"] == "result_auto_fetched"
    assert data["last_sync_at"] is not None
    assert data["next_run_at"] is not None
    assert data["recent_errors"] == []


@pytest.mark.asyncio
async def test_sync_status_exposes_recent_errors() -> None:
    """recent_errors contains sync_failed audit rows."""
    admin = _make_admin()
    mock_db = AsyncMock(spec=AsyncSession)

    ts = _now()
    last_audit = _make_audit(ActionType.sync_failed, ts)
    err1 = _make_audit(ActionType.sync_failed, ts)
    err2 = _make_audit(ActionType.sync_failed, ts)

    last_result = MagicMock()
    last_result.scalar_one_or_none.return_value = last_audit
    errors_result = MagicMock()
    errors_result.scalars.return_value.all.return_value = [err1, err2]
    mock_db.execute = AsyncMock(side_effect=[last_result, errors_result])

    async def _db_override() -> AsyncGenerator[AsyncMock, None]:
        yield mock_db

    app.dependency_overrides[get_db] = _db_override
    app.dependency_overrides[require_admin] = lambda: admin
    app.state.scheduler = _build_mock_scheduler()

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/admin/sync/status")
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(require_admin, None)

    assert resp.status_code == 200
    data = resp.json()
    assert data["last_sync_action"] == "sync_failed"
    assert len(data["recent_errors"]) == 2
    assert data["recent_errors"][0]["action_type"] == "sync_failed"


@pytest.mark.asyncio
async def test_sync_status_requires_admin() -> None:
    """Unauthenticated request returns 401."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/admin/sync/status")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/v1/admin/sync/trigger
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_sync_calls_sync_results() -> None:
    """Trigger endpoint calls sync_results() and returns updated status."""
    admin = _make_admin()
    mock_db = AsyncMock(spec=AsyncSession)

    ts = _now()
    audit = _make_audit(ActionType.sync_triggered, ts)
    last_result = MagicMock()
    last_result.scalar_one_or_none.return_value = audit
    errors_result = MagicMock()
    errors_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(side_effect=[last_result, errors_result])

    async def _db_override() -> AsyncGenerator[AsyncMock, None]:
        yield mock_db

    app.dependency_overrides[get_db] = _db_override
    app.dependency_overrides[require_admin] = lambda: admin
    app.state.scheduler = _build_mock_scheduler()

    with patch("src.routers.admin.sync_results", new_callable=AsyncMock) as mock_sync:
        try:
            async with AsyncClient(  # noqa: E501
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post("/api/v1/admin/sync/trigger")
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(require_admin, None)
        mock_sync.assert_awaited_once()

    assert resp.status_code == 200
    data = resp.json()
    assert "last_sync_at" in data


@pytest.mark.asyncio
async def test_trigger_sync_requires_admin() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/v1/admin/sync/trigger")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/v1/admin/results
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_results_returns_completed_matches() -> None:
    """Returns completed matches with result_source field."""
    admin = _make_admin()
    mock_db = AsyncMock(spec=AsyncSession)

    m1 = _make_match(result_source=ResultSource.auto)
    m2 = _make_match(result_source=ResultSource.manual)

    matches_result = MagicMock()
    matches_result.scalars.return_value.all.return_value = [m1, m2]
    teams_result = MagicMock()
    teams_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(side_effect=[matches_result, teams_result])

    async def _db_override() -> AsyncGenerator[AsyncMock, None]:
        yield mock_db

    app.dependency_overrides[get_db] = _db_override
    app.dependency_overrides[require_admin] = lambda: admin

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/admin/results")
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(require_admin, None)

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    sources = {r["result_source"] for r in data}
    assert sources == {"auto", "manual"}


@pytest.mark.asyncio
async def test_list_results_empty() -> None:
    """Returns empty list when no completed matches."""
    admin = _make_admin()
    mock_db = AsyncMock(spec=AsyncSession)

    empty = MagicMock()
    empty.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(return_value=empty)

    async def _db_override() -> AsyncGenerator[AsyncMock, None]:
        yield mock_db

    app.dependency_overrides[get_db] = _db_override
    app.dependency_overrides[require_admin] = lambda: admin

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/admin/results")
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(require_admin, None)

    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_results_requires_admin() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/admin/results")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/v1/admin/results/pending (GAP-02 manual-entry fallback)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_pending_results_returns_matches_awaiting_result() -> None:
    """Returns locked/live matches that have no result, with team ids + stage."""
    admin = _make_admin()
    mock_db = AsyncMock(spec=AsyncSession)

    m = _make_match(result_source=None, home_score=None, away_score=None)
    m.status = MatchStatus.locked
    m.stage = TournamentStage.r16
    home_id = uuid.uuid4()
    away_id = uuid.uuid4()
    m.home_team_id = home_id
    m.away_team_id = away_id

    matches_result = MagicMock()
    matches_result.scalars.return_value.all.return_value = [m]
    teams_result = MagicMock()
    teams_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(side_effect=[matches_result, teams_result])

    async def _db_override() -> AsyncGenerator[AsyncMock, None]:
        yield mock_db

    app.dependency_overrides[get_db] = _db_override
    app.dependency_overrides[require_admin] = lambda: admin

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/admin/results/pending")
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(require_admin, None)

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["result_source"] is None
    assert data[0]["stage"] == "r16"
    assert data[0]["home_team_id"] == str(home_id)
    assert data[0]["away_team_id"] == str(away_id)


@pytest.mark.asyncio
async def test_list_pending_results_requires_admin() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/admin/results/pending")
    assert resp.status_code == 401
