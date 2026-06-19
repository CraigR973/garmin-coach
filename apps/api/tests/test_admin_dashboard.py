"""Tests for Phase 5.6 admin dashboard endpoint."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import require_admin
from src.database import get_db
from src.main import app
from src.models.match import Match, MatchStatus
from src.models.notification import ActionType, ActorType, AuditLog
from src.models.profile import PlayerRole, Profile

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


def _make_player(deleted: bool = False) -> MagicMock:
    p = MagicMock(spec=Profile)
    p.avatar_url = None  # U23: prevent MagicMock default from failing Pydantic
    p.id = uuid.uuid4()
    p.deleted_at = _now() if deleted else None
    return p


def _make_match(
    *,
    status: MatchStatus,
    kickoff_offset_mins: int = 60,
) -> MagicMock:
    m = MagicMock(spec=Match)
    m.id = uuid.uuid4()
    m.match_number = 1
    m.status = status
    m.kickoff_utc = _now() + timedelta(minutes=kickoff_offset_mins)
    m.result_source = None
    m.actual_home_score = None
    m.actual_away_score = None
    m.extra_time = False
    m.penalties = False
    m.result_entered_at = None
    m.home_team_id = None
    m.away_team_id = None
    m.home_team_placeholder = "Home"
    m.away_team_placeholder = "Away"
    m.deleted_at = None
    return m


def _make_audit(action: ActionType) -> MagicMock:
    a = MagicMock(spec=AuditLog)
    a.id = uuid.uuid4()
    a.actor_type = ActorType.admin
    a.action_type = action
    a.timestamp = _now()
    a.target_table = "matches"
    a.changes = None
    return a


def _build_mock_scheduler() -> MagicMock:
    scheduler = MagicMock()
    job = MagicMock()
    job.next_run_time = _now() + timedelta(minutes=5)
    scheduler.get_job.return_value = job
    return scheduler


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dashboard_returns_all_sections() -> None:
    """Dashboard endpoint returns all required sections."""
    admin = _make_admin()
    mock_db = AsyncMock(spec=AsyncSession)

    # Query 1: active players
    player1 = _make_player()
    player2 = _make_player()
    players_result = MagicMock()
    players_result.scalars.return_value.all.return_value = [player1, player2]

    # Query 2: upcoming locks
    upcoming_match = _make_match(status=MatchStatus.scheduled, kickoff_offset_mins=120)
    locks_result = MagicMock()
    locks_result.scalars.return_value.all.return_value = [upcoming_match]

    # Query 3: pending results
    pending_match = _make_match(status=MatchStatus.locked, kickoff_offset_mins=-30)
    pending_db_result = MagicMock()
    pending_db_result.scalars.return_value.all.return_value = [pending_match]

    # Query 4: recent audit (team query skipped — all team_ids are None)
    audit_entry = _make_audit(ActionType.result_manual_entered)
    audit_result = MagicMock()
    audit_result.scalars.return_value.all.return_value = [audit_entry]

    # Queries 5-6: sync status (last row + errors)
    sync_last = MagicMock()
    sync_last.scalar_one_or_none.return_value = None
    sync_errors = MagicMock()
    sync_errors.scalars.return_value.all.return_value = []

    mock_db.execute = AsyncMock(
        side_effect=[
            players_result,
            locks_result,
            pending_db_result,
            audit_result,
            sync_last,
            sync_errors,
        ]
    )

    async def _db_override() -> AsyncGenerator[AsyncMock, None]:
        yield mock_db

    app.dependency_overrides[get_db] = _db_override
    app.dependency_overrides[require_admin] = lambda: admin
    app.state.scheduler = _build_mock_scheduler()

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/admin/dashboard")
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(require_admin, None)

    assert resp.status_code == 200
    data = resp.json()
    assert data["active_players"] == 2
    assert len(data["upcoming_locks"]) == 1
    assert len(data["pending_result_matches"]) == 1
    assert len(data["recent_audit"]) == 1
    assert "sync_status" in data


@pytest.mark.asyncio
async def test_dashboard_empty_state() -> None:
    """Dashboard returns zeros and empty lists when nothing is happening."""
    admin = _make_admin()
    mock_db = AsyncMock(spec=AsyncSession)

    empty_list = MagicMock()
    empty_list.scalars.return_value.all.return_value = []
    sync_none = MagicMock()
    sync_none.scalar_one_or_none.return_value = None

    mock_db.execute = AsyncMock(
        side_effect=[
            empty_list,  # players
            empty_list,  # upcoming locks
            empty_list,  # pending results (team query skipped — no non-None IDs)
            empty_list,  # audit
            sync_none,  # sync last row
            empty_list,  # sync errors
        ]
    )

    async def _db_override() -> AsyncGenerator[AsyncMock, None]:
        yield mock_db

    app.dependency_overrides[get_db] = _db_override
    app.dependency_overrides[require_admin] = lambda: admin
    app.state.scheduler = _build_mock_scheduler()

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/admin/dashboard")
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(require_admin, None)

    assert resp.status_code == 200
    data = resp.json()
    assert data["active_players"] == 0
    assert data["upcoming_locks"] == []
    assert data["pending_result_matches"] == []
    assert data["recent_audit"] == []


@pytest.mark.asyncio
async def test_dashboard_requires_admin() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/admin/dashboard")
    assert resp.status_code == 401
