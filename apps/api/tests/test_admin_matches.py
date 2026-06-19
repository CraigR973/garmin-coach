"""Tests for admin match endpoints: reschedule, postpone, cancel."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.auth import require_admin
from src.database import get_db
from src.main import app
from src.models.match import Match, MatchStatus
from src.models.notification import ActionType, ActorType, AuditLog
from src.models.profile import PlayerRole, Profile


@pytest.fixture(autouse=True)
def _no_notify_admin() -> None:
    with (
        patch("src.routers.admin.notify_kickoff_changed", new_callable=AsyncMock),
        patch("src.routers.admin.notify_match_postponed", new_callable=AsyncMock),
    ):
        yield


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _make_admin() -> Profile:
    p = MagicMock(spec=Profile)
    p.avatar_url = None  # U23: prevent MagicMock default from failing Pydantic
    p.id = uuid.uuid4()
    p.display_name = "Admin"
    p.role = PlayerRole.admin
    p.deleted_at = None
    return p


def _make_match(
    *,
    status: MatchStatus = MatchStatus.scheduled,
    kickoff: datetime | None = None,
    original_kickoff: datetime | None = None,
    locked_at: datetime | None = None,
) -> Match:
    m = MagicMock(spec=Match)
    m.id = uuid.uuid4()
    m.match_number = 1
    m.status = status
    m.kickoff_utc = kickoff or _now()
    m.original_kickoff_utc = original_kickoff
    m.locked_at = locked_at
    m.postponed_reason = None
    m.deleted_at = None
    return m


def _scalar(value: object) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _stub_db(execute_results: list) -> AsyncMock:
    mock_db = AsyncMock(spec=AsyncSession)
    mock_db.execute = AsyncMock(side_effect=execute_results)
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock(side_effect=lambda obj: None)
    mock_db.add = MagicMock()
    return mock_db


@asynccontextmanager
async def _override(mock_db: AsyncMock, admin: Profile) -> AsyncGenerator[None, None]:
    async def _fake_db() -> AsyncGenerator[AsyncSession, None]:
        yield mock_db

    async def _fake_admin() -> Profile:
        return admin

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[require_admin] = _fake_admin
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(require_admin, None)


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def _audit_rows(db: AsyncMock) -> list[AuditLog]:
    return [c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], AuditLog)]


# ---------------------------------------------------------------------------
# Reschedule
# ---------------------------------------------------------------------------


async def test_reschedule_match_updates_kickoff_and_sets_original(client: AsyncClient) -> None:
    admin = _make_admin()
    original = _now() + timedelta(days=1)
    new_kickoff = original + timedelta(hours=2)
    match = _make_match(kickoff=original)
    db = _stub_db([_scalar(match)])

    async with _override(db, admin):
        resp = await client.post(
            f"/api/v1/admin/matches/{match.id}/reschedule",
            json={"kickoff_utc": new_kickoff.isoformat()},
        )

    assert resp.status_code == 200, resp.text
    assert match.kickoff_utc == new_kickoff
    assert match.original_kickoff_utc == original
    rows = _audit_rows(db)
    assert len(rows) == 1
    assert rows[0].actor_type == ActorType.admin
    assert rows[0].action_type == ActionType.kickoff_changed


async def test_reschedule_preserves_existing_original_kickoff(client: AsyncClient) -> None:
    admin = _make_admin()
    first_original = _now() - timedelta(days=2)
    current_kickoff = _now() + timedelta(days=1)
    new_kickoff = current_kickoff + timedelta(hours=3)
    match = _make_match(kickoff=current_kickoff, original_kickoff=first_original)
    db = _stub_db([_scalar(match)])

    async with _override(db, admin):
        resp = await client.post(
            f"/api/v1/admin/matches/{match.id}/reschedule",
            json={"kickoff_utc": new_kickoff.isoformat()},
        )

    assert resp.status_code == 200
    assert match.original_kickoff_utc == first_original


async def test_reschedule_relocks_when_locked_and_new_kickoff_future(client: AsyncClient) -> None:
    admin = _make_admin()
    locked_at = _now() - timedelta(minutes=5)
    new_kickoff = _now() + timedelta(hours=2)
    match = _make_match(
        status=MatchStatus.locked,
        kickoff=_now() - timedelta(minutes=4),
        locked_at=locked_at,
    )
    db = _stub_db([_scalar(match)])

    async with _override(db, admin):
        resp = await client.post(
            f"/api/v1/admin/matches/{match.id}/reschedule",
            json={"kickoff_utc": new_kickoff.isoformat()},
        )

    assert resp.status_code == 200
    assert match.status == MatchStatus.scheduled
    assert match.locked_at is None


async def test_reschedule_match_not_found(client: AsyncClient) -> None:
    admin = _make_admin()
    db = _stub_db([_scalar(None)])

    async with _override(db, admin):
        resp = await client.post(
            f"/api/v1/admin/matches/{uuid.uuid4()}/reschedule",
            json={"kickoff_utc": _now().isoformat()},
        )

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Postpone
# ---------------------------------------------------------------------------


async def test_postpone_match_sets_status_and_reason(client: AsyncClient) -> None:
    admin = _make_admin()
    match = _make_match()
    db = _stub_db([_scalar(match)])

    async with _override(db, admin):
        resp = await client.post(
            f"/api/v1/admin/matches/{match.id}/postpone",
            json={"reason": "Severe weather"},
        )

    assert resp.status_code == 200
    assert match.status == MatchStatus.postponed
    assert match.postponed_reason == "Severe weather"
    rows = _audit_rows(db)
    assert len(rows) == 1
    assert rows[0].action_type == ActionType.match_postponed
    assert rows[0].changes == {"reason": "Severe weather"}


async def test_postpone_match_not_found(client: AsyncClient) -> None:
    admin = _make_admin()
    db = _stub_db([_scalar(None)])

    async with _override(db, admin):
        resp = await client.post(
            f"/api/v1/admin/matches/{uuid.uuid4()}/postpone",
            json={"reason": "x"},
        )

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------


async def test_cancel_match_sets_status_and_writes_audit(client: AsyncClient) -> None:
    admin = _make_admin()
    match = _make_match()
    # _load_match → select(Match); then two UPDATE statements (predictions,
    # knockout_predictions) — those return values are ignored by the route.
    db = _stub_db([_scalar(match), MagicMock(), MagicMock()])

    with patch("src.routers.admin.recompute_leaderboard_snapshot", new_callable=AsyncMock):
        async with _override(db, admin):
            resp = await client.post(f"/api/v1/admin/matches/{match.id}/cancel")

    assert resp.status_code == 200
    assert match.status == MatchStatus.cancelled
    rows = _audit_rows(db)
    assert len(rows) == 1
    assert rows[0].action_type == ActionType.match_cancelled


async def test_cancel_match_zeroes_points_and_recomputes_snapshot(
    client: AsyncClient,
) -> None:
    """Wiring: cancel zeroes predictions + knockout points, then calls helper.

    Without these writes a cancelled match keeps awarding points to the
    predictions it had before cancellation (spec §6.13).
    """
    admin = _make_admin()
    match = _make_match()
    db = _stub_db([_scalar(match), MagicMock(), MagicMock()])

    with patch(
        "src.routers.admin.recompute_leaderboard_snapshot", new_callable=AsyncMock
    ) as mock_helper:
        async with _override(db, admin):
            resp = await client.post(f"/api/v1/admin/matches/{match.id}/cancel")

    assert resp.status_code == 200
    # Two UPDATE statements (predictions, knockout_predictions) plus the
    # initial _load_match SELECT = 3 execute() calls total.
    assert db.execute.await_count == 3
    mock_helper.assert_awaited_once()
    _, kwargs = mock_helper.await_args
    assert kwargs.get("triggered_by_match_id") == match.id


async def test_cancel_match_not_found(client: AsyncClient) -> None:
    admin = _make_admin()
    db = _stub_db([_scalar(None)])

    async with _override(db, admin):
        resp = await client.post(f"/api/v1/admin/matches/{uuid.uuid4()}/cancel")

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Lock (GAP-07)
# ---------------------------------------------------------------------------


async def test_lock_match_sets_status_and_writes_audit(client: AsyncClient) -> None:
    admin = _make_admin()
    match = _make_match(status=MatchStatus.scheduled)
    db = _stub_db([_scalar(match)])

    async with _override(db, admin):
        resp = await client.post(f"/api/v1/admin/matches/{match.id}/lock")

    assert resp.status_code == 200, resp.text
    assert match.status == MatchStatus.locked
    rows = _audit_rows(db)
    assert len(rows) == 1
    assert rows[0].action_type == ActionType.match_locked
    assert rows[0].actor_type == ActorType.admin


async def test_lock_already_locked_is_idempotent(client: AsyncClient) -> None:
    admin = _make_admin()
    match = _make_match(status=MatchStatus.locked)
    db = _stub_db([_scalar(match)])

    async with _override(db, admin):
        resp = await client.post(f"/api/v1/admin/matches/{match.id}/lock")

    assert resp.status_code == 200
    # No new audit row because it was already locked — just returns the match.
    rows = _audit_rows(db)
    assert len(rows) == 0


async def test_lock_completed_match_is_conflict(client: AsyncClient) -> None:
    admin = _make_admin()
    match = _make_match(status=MatchStatus.completed)
    db = _stub_db([_scalar(match)])

    async with _override(db, admin):
        resp = await client.post(f"/api/v1/admin/matches/{match.id}/lock")

    assert resp.status_code == 409


async def test_lock_match_not_found(client: AsyncClient) -> None:
    admin = _make_admin()
    db = _stub_db([_scalar(None)])

    async with _override(db, admin):
        resp = await client.post(f"/api/v1/admin/matches/{uuid.uuid4()}/lock")

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------


async def test_admin_match_endpoints_require_auth(client: AsyncClient) -> None:
    resp = await client.post(
        f"/api/v1/admin/matches/{uuid.uuid4()}/cancel",
    )
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# R2.5 — integration: cancel zeroes the match contribution in the snapshot
# ---------------------------------------------------------------------------


async def _exec_raw(conn: AsyncConnection, sql: str, **params: Any) -> Any:
    return await conn.execute(text(sql), params)


async def _scalar_raw(conn: AsyncConnection, sql: str, **params: Any) -> Any:
    result = await conn.execute(text(sql), params)
    return result.scalar_one()


async def _fetchall_raw(conn: AsyncConnection, sql: str, **params: Any) -> list[Any]:
    result = await conn.execute(text(sql), params)
    return list(result.mappings().all())


async def _insert_group_raw(conn: AsyncConnection, name: str) -> uuid.UUID:
    return await _scalar_raw(
        conn,
        "INSERT INTO groups (id, name) VALUES (gen_random_uuid(), :n) RETURNING id",
        n=name,
    )


async def _insert_team_raw(
    conn: AsyncConnection, group_id: uuid.UUID, name: str, code: str
) -> uuid.UUID:
    return await _scalar_raw(
        conn,
        """
        INSERT INTO teams (id, name, code, flag_emoji, group_id, is_host)
        VALUES (gen_random_uuid(), :n, :c, '🏳', :g, FALSE) RETURNING id
        """,
        n=name,
        c=code,
        g=group_id,
    )


async def _insert_profile_raw(conn: AsyncConnection, display_name: str) -> uuid.UUID:
    profile_id = await _scalar_raw(
        conn,
        """
        INSERT INTO profiles (
            id, display_name, pin_hash, role, deleted_at, email,
            first_name, last_name, site_role
        )
        VALUES (
            gen_random_uuid(), :n,
            '$2b$12$0000000000000000000000000000000000000000000000000000',
            'player', NULL, :email,
            'Test', 'User', CAST('user' AS site_role)
        ) RETURNING id
        """,
        n=display_name,
        email=f"{display_name}@test.invalid",
    )
    # M2: snapshots fan out per active league membership. The recompute
    # helper called by this test needs a membership row to write to.
    from tests.conftest import ensure_default_league_membership

    await ensure_default_league_membership(conn, profile_id)
    return profile_id


async def test_cancel_match_snapshot_reflects_zero_contribution(
    db_conn: AsyncConnection,
) -> None:
    """After cancelling a completed match, snapshot shows zero from that match.

    Mirrors the runtime cancel flow without spinning up the FastAPI route:
    zero out predictions.points_awarded / knockout_predictions.points_awarded
    for the cancelled match, then run the helper. The latest snapshot for the
    player must reflect the lost match contribution.
    """
    from src.services.leaderboard import recompute_leaderboard_snapshot

    g = await _insert_group_raw(db_conn, "C")
    home = await _insert_team_raw(db_conn, g, "Cancel A", "CCA")
    away = await _insert_team_raw(db_conn, g, "Cancel B", "CCB")
    alice = await _insert_profile_raw(db_conn, "alice_cancel_snap")

    # alice predicted 2-1 exactly, scoring 10 match points when the result lands.
    match_id = await _scalar_raw(
        db_conn,
        """
        INSERT INTO matches (id, stage, group_id, match_number, home_team_id,
            away_team_id, kickoff_utc, status)
        VALUES (gen_random_uuid(), 'group', :g, 970, :h, :a, '2026-06-13 18:00:00', 'locked')
        RETURNING id
        """,
        g=g,
        h=home,
        a=away,
    )
    await _exec_raw(
        db_conn,
        """
        INSERT INTO predictions (id, player_id, match_id, predicted_home, predicted_away)
        VALUES (gen_random_uuid(), :p, :m, 2, 1)
        """,
        p=alice,
        m=match_id,
    )
    await _exec_raw(
        db_conn,
        """
        UPDATE matches SET actual_home_score = 2, actual_away_score = 1,
            status = 'completed', result_source = 'manual'
        WHERE id = :m
        """,
        m=match_id,
    )
    pts_before = await _scalar_raw(
        db_conn,
        "SELECT points_awarded FROM predictions WHERE match_id = :m",
        m=match_id,
    )
    assert pts_before == 10

    # Now mimic cancel_match: status → cancelled, zero points, recompute snapshot.
    await _exec_raw(
        db_conn,
        "UPDATE matches SET status = 'cancelled' WHERE id = :m",
        m=match_id,
    )
    await _exec_raw(
        db_conn,
        "UPDATE predictions SET points_awarded = 0 WHERE match_id = :m",
        m=match_id,
    )
    await _exec_raw(
        db_conn,
        "UPDATE knockout_predictions SET points_awarded = 0 WHERE match_id = :m",
        m=match_id,
    )

    session = AsyncSession(bind=db_conn, expire_on_commit=False)
    try:
        await recompute_leaderboard_snapshot(session, triggered_by_match_id=match_id)
    finally:
        await session.close()

    pts_after = await _scalar_raw(
        db_conn,
        "SELECT points_awarded FROM predictions WHERE match_id = :m",
        m=match_id,
    )
    assert pts_after == 0

    latest = await _fetchall_raw(
        db_conn,
        """
        SELECT match_points, total_points, triggered_by_match_id
        FROM leaderboard_snapshots
        WHERE player_id = :p
        ORDER BY snapshot_at DESC
        LIMIT 1
        """,
        p=alice,
    )
    assert latest[0]["match_points"] == 0
    assert latest[0]["total_points"] == 0
    assert latest[0]["triggered_by_match_id"] == match_id
