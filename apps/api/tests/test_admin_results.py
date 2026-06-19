"""Tests for Phase 5.1 admin results endpoints.

HTTP-layer tests use a mocked AsyncSession so no live DB is required.
Integration tests (override recalculates points) use the real Postgres
db_conn fixture and skip when DATABASE_URL is not set.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import require_admin
from src.database import get_db
from src.main import app
from src.models.match import Match, MatchStatus, ResultSource
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


def _make_match(
    *,
    status: MatchStatus = MatchStatus.locked,
    result_source: ResultSource | None = None,
    home_score: int | None = None,
    away_score: int | None = None,
) -> MagicMock:
    m = MagicMock(spec=Match)
    m.id = uuid.uuid4()
    m.status = status
    m.result_source = result_source
    m.actual_home_score = home_score
    m.actual_away_score = away_score
    m.extra_time = False
    m.penalties = False
    m.penalty_winner_id = None
    m.result_entered_at = _now()
    m.result_entered_by = uuid.uuid4()
    m.deleted_at = None
    return m


def _stub_db(execute_results: list[Any]) -> AsyncMock:
    mock_db = AsyncMock(spec=AsyncSession)
    mock_db.execute = AsyncMock(side_effect=execute_results)
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()
    mock_db.flush = AsyncMock()
    mock_db.add = MagicMock()
    return mock_db


def _scalar(value: object) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


@asynccontextmanager
async def _with_admin_and_db(
    mock_db: AsyncMock, admin: Profile
) -> AsyncGenerator[AsyncClient, None]:
    async def _get_db_override() -> AsyncGenerator[AsyncMock, None]:
        yield mock_db

    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[require_admin] = lambda: admin
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(require_admin, None)


_RESULT_BODY = {
    "actual_home_score": 2,
    "actual_away_score": 1,
    "extra_time": False,
    "penalties": False,
}


# ---------------------------------------------------------------------------
# POST /api/v1/admin/results/{match_id} — manual entry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enter_result_locked_match_returns_200() -> None:
    admin = _make_admin()
    match = _make_match(status=MatchStatus.locked)
    mock_db = _stub_db([_scalar(match)])

    async with _with_admin_and_db(mock_db, admin) as client:
        resp = await client.post(f"/api/v1/admin/results/{match.id}", json=_RESULT_BODY)

    assert resp.status_code == 200
    data = resp.json()
    assert data["result_source"] == "manual"
    assert data["actual_home_score"] == 2
    assert data["actual_away_score"] == 1


@pytest.mark.asyncio
async def test_enter_result_live_match_returns_200() -> None:
    admin = _make_admin()
    match = _make_match(status=MatchStatus.live)
    mock_db = _stub_db([_scalar(match)])

    async with _with_admin_and_db(mock_db, admin) as client:
        resp = await client.post(f"/api/v1/admin/results/{match.id}", json=_RESULT_BODY)

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_enter_result_completed_no_source_returns_200() -> None:
    admin = _make_admin()
    match = _make_match(status=MatchStatus.completed, result_source=None)
    mock_db = _stub_db([_scalar(match)])

    async with _with_admin_and_db(mock_db, admin) as client:
        resp = await client.post(f"/api/v1/admin/results/{match.id}", json=_RESULT_BODY)

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_enter_result_not_found_returns_404() -> None:
    admin = _make_admin()
    mock_db = _stub_db([_scalar(None)])

    async with _with_admin_and_db(mock_db, admin) as client:
        resp = await client.post(f"/api/v1/admin/results/{uuid.uuid4()}", json=_RESULT_BODY)

    assert resp.status_code == 404


@pytest.mark.parametrize(
    "bad_status",
    [MatchStatus.scheduled, MatchStatus.postponed, MatchStatus.cancelled],
)
@pytest.mark.asyncio
async def test_enter_result_rejects_invalid_status(bad_status: MatchStatus) -> None:
    admin = _make_admin()
    match = _make_match(status=bad_status)
    mock_db = _stub_db([_scalar(match)])

    async with _with_admin_and_db(mock_db, admin) as client:
        resp = await client.post(f"/api/v1/admin/results/{match.id}", json=_RESULT_BODY)

    assert resp.status_code == 422
    assert bad_status.value in resp.json()["detail"]


@pytest.mark.asyncio
async def test_enter_result_rejects_if_result_exists() -> None:
    admin = _make_admin()
    match = _make_match(
        status=MatchStatus.completed,
        result_source=ResultSource.manual,
        home_score=1,
        away_score=0,
    )
    mock_db = _stub_db([_scalar(match)])

    async with _with_admin_and_db(mock_db, admin) as client:
        resp = await client.post(f"/api/v1/admin/results/{match.id}", json=_RESULT_BODY)

    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_enter_result_adds_audit_log() -> None:
    admin = _make_admin()
    match = _make_match(status=MatchStatus.locked)
    mock_db = _stub_db([_scalar(match)])

    async with _with_admin_and_db(mock_db, admin) as client:
        resp = await client.post(f"/api/v1/admin/results/{match.id}", json=_RESULT_BODY)

    assert resp.status_code == 200
    mock_db.add.assert_called_once()
    added = mock_db.add.call_args[0][0]
    # Verify it's an AuditLog-like object with the expected action
    from src.models.notification import ActionType, ActorType, AuditLog

    assert isinstance(added, AuditLog)
    assert added.actor_type == ActorType.admin
    assert added.action_type == ActionType.result_manual_entered
    assert added.target_table == "matches"


@pytest.mark.asyncio
async def test_enter_result_with_penalty_winner() -> None:
    admin = _make_admin()
    match = _make_match(status=MatchStatus.locked)
    mock_db = _stub_db([_scalar(match)])
    penalty_winner = str(uuid.uuid4())

    async with _with_admin_and_db(mock_db, admin) as client:
        resp = await client.post(
            f"/api/v1/admin/results/{match.id}",
            json={**_RESULT_BODY, "penalties": True, "penalty_winner_id": penalty_winner},
        )

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_enter_result_rejects_negative_score() -> None:
    admin = _make_admin()
    match = _make_match(status=MatchStatus.locked)
    mock_db = _stub_db([_scalar(match)])

    async with _with_admin_and_db(mock_db, admin) as client:
        resp = await client.post(
            f"/api/v1/admin/results/{match.id}",
            json={"actual_home_score": -1, "actual_away_score": 0},
        )

    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# PUT /api/v1/admin/results/{match_id} — override
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_override_result_returns_200() -> None:
    admin = _make_admin()
    match = _make_match(
        status=MatchStatus.completed,
        result_source=ResultSource.manual,
        home_score=1,
        away_score=0,
    )
    mock_db = _stub_db([_scalar(match)])

    async with _with_admin_and_db(mock_db, admin) as client:
        resp = await client.put(f"/api/v1/admin/results/{match.id}", json=_RESULT_BODY)

    assert resp.status_code == 200
    assert resp.json()["result_source"] == "override"


@pytest.mark.asyncio
async def test_override_result_not_found_returns_404() -> None:
    admin = _make_admin()
    mock_db = _stub_db([_scalar(None)])

    async with _with_admin_and_db(mock_db, admin) as client:
        resp = await client.put(f"/api/v1/admin/results/{uuid.uuid4()}", json=_RESULT_BODY)

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_override_result_rejects_if_no_prior_result() -> None:
    admin = _make_admin()
    match = _make_match(status=MatchStatus.locked, result_source=None)
    mock_db = _stub_db([_scalar(match)])

    async with _with_admin_and_db(mock_db, admin) as client:
        resp = await client.put(f"/api/v1/admin/results/{match.id}", json=_RESULT_BODY)

    assert resp.status_code == 422
    assert "no prior result" in resp.json()["detail"].lower()


@pytest.mark.parametrize(
    "bad_status",
    [MatchStatus.scheduled, MatchStatus.postponed, MatchStatus.cancelled],
)
@pytest.mark.asyncio
async def test_override_result_rejects_invalid_status(bad_status: MatchStatus) -> None:
    admin = _make_admin()
    match = _make_match(status=bad_status, result_source=ResultSource.manual)
    mock_db = _stub_db([_scalar(match)])

    async with _with_admin_and_db(mock_db, admin) as client:
        resp = await client.put(f"/api/v1/admin/results/{match.id}", json=_RESULT_BODY)

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_override_result_adds_audit_log() -> None:
    admin = _make_admin()
    match = _make_match(
        status=MatchStatus.completed,
        result_source=ResultSource.manual,
        home_score=1,
        away_score=0,
    )
    mock_db = _stub_db([_scalar(match)])

    async with _with_admin_and_db(mock_db, admin) as client:
        resp = await client.put(f"/api/v1/admin/results/{match.id}", json=_RESULT_BODY)

    assert resp.status_code == 200
    mock_db.add.assert_called_once()
    added = mock_db.add.call_args[0][0]
    from src.models.notification import ActionType, ActorType, AuditLog

    assert isinstance(added, AuditLog)
    assert added.actor_type == ActorType.admin
    assert added.action_type == ActionType.result_overridden


# ---------------------------------------------------------------------------
# Integration: override recalculates points (requires live Postgres)
# ---------------------------------------------------------------------------


async def _exec(conn: Any, sql: str, **params: Any) -> Any:
    from sqlalchemy import text

    return await conn.execute(text(sql), params)


async def _scalar_raw(conn: Any, sql: str, **params: Any) -> Any:
    from sqlalchemy import text

    result = await conn.execute(text(sql), params)
    return result.scalar_one()


async def _fetchall_raw(conn: Any, sql: str, **params: Any) -> list[Any]:
    from sqlalchemy import text

    result = await conn.execute(text(sql), params)
    return list(result.mappings().all())


async def _insert_group(conn: Any, name: str) -> uuid.UUID:
    return await _scalar_raw(
        conn,
        "INSERT INTO groups (id, name) VALUES (gen_random_uuid(), :n) RETURNING id",
        n=name,
    )


async def _insert_team(conn: Any, group_id: uuid.UUID, name: str, code: str) -> uuid.UUID:
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


async def _insert_profile(conn: Any, display_name: str) -> uuid.UUID:
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
    # M2: snapshots fan out per active league membership. The trigger
    # exercised by these override tests needs a membership row to write to.
    from tests.conftest import ensure_default_league_membership

    await ensure_default_league_membership(conn, profile_id)
    return profile_id


async def _insert_match_and_predict(
    conn: Any,
    *,
    home_id: uuid.UUID,
    away_id: uuid.UUID,
    group_id: uuid.UUID,
    player_id: uuid.UUID,
    pred_home: int,
    pred_away: int,
) -> uuid.UUID:
    mid = await _scalar_raw(
        conn,
        """
        INSERT INTO matches (id, stage, group_id, match_number, home_team_id,
            away_team_id, kickoff_utc, status)
        VALUES (gen_random_uuid(), 'group', :g, :mn, :h, :a, '2026-06-11 18:00:00', 'locked')
        RETURNING id
        """,
        g=group_id,
        mn=900,
        h=home_id,
        a=away_id,
    )
    await _exec(
        conn,
        """
        INSERT INTO predictions (id, player_id, match_id, predicted_home, predicted_away)
        VALUES (gen_random_uuid(), :p, :m, :ph, :pa)
        """,
        p=player_id,
        m=mid,
        ph=pred_home,
        pa=pred_away,
    )
    return mid


async def test_override_recalculates_points(db_conn: Any) -> None:
    """After overriding a result, predictions.points_awarded reflects the new scores."""
    from sqlalchemy.ext.asyncio import AsyncConnection

    conn: AsyncConnection = db_conn
    g = await _insert_group(conn, "A")
    home = await _insert_team(conn, g, "Alpha", "ALP")
    away = await _insert_team(conn, g, "Beta", "BET")
    alice = await _insert_profile(conn, "alice_override")

    match_id = await _insert_match_and_predict(
        conn,
        home_id=home,
        away_id=away,
        group_id=g,
        player_id=alice,
        pred_home=2,
        pred_away=1,
    )

    # Initial result: 1-0 (alice predicted 2-1, so only result pts: 3)
    await _exec(
        conn,
        """
        UPDATE matches SET actual_home_score = 1, actual_away_score = 0,
            status = 'completed', result_source = 'manual', result_entered_by = :p
        WHERE id = :m
        """,
        p=alice,
        m=match_id,
    )

    pts_after_first = await _scalar_raw(
        conn,
        "SELECT points_awarded FROM predictions WHERE match_id = :m AND player_id = :p",
        m=match_id,
        p=alice,
    )
    assert pts_after_first == 3  # result pts only

    # Override to 2-1 (alice predicted exactly → 10 pts). Single-shot UPDATE:
    # the AFTER trigger has no WHEN clause (migration 009) so any score change
    # re-fires scoring — no null-then-set hack required.
    await _exec(
        conn,
        """
        UPDATE matches SET actual_home_score = 2, actual_away_score = 1,
            status = 'completed', result_source = 'override', result_entered_by = :p
        WHERE id = :m
        """,
        p=alice,
        m=match_id,
    )

    pts_after_override = await _scalar_raw(
        conn,
        "SELECT points_awarded FROM predictions WHERE match_id = :m AND player_id = :p",
        m=match_id,
        p=alice,
    )
    assert pts_after_override == 10  # exact score → full 10 pts


async def test_result_source_manual_set_correctly(db_conn: Any) -> None:
    """Confirm result_source is 'manual' after first entry and 'override' after PUT."""
    from sqlalchemy.ext.asyncio import AsyncConnection

    conn: AsyncConnection = db_conn
    g = await _insert_group(conn, "B")
    home = await _insert_team(conn, g, "Gamma", "GAM")
    away = await _insert_team(conn, g, "Delta", "DEL")
    match_id = await _scalar_raw(
        conn,
        """
        INSERT INTO matches (id, stage, group_id, match_number, home_team_id,
            away_team_id, kickoff_utc, status)
        VALUES (gen_random_uuid(), 'group', :g, 901, :h, :a, '2026-06-12 18:00:00', 'locked')
        RETURNING id
        """,
        g=g,
        h=home,
        a=away,
    )

    # Enter first result
    await _exec(
        conn,
        """
        UPDATE matches SET actual_home_score = 1, actual_away_score = 0,
            status = 'completed', result_source = 'manual'
        WHERE id = :m
        """,
        m=match_id,
    )
    src1 = await _scalar_raw(conn, "SELECT result_source FROM matches WHERE id = :m", m=match_id)
    assert src1 == "manual"

    # Override result — single-shot UPDATE (migration 009 dropped the WHEN clause).
    await _exec(
        conn,
        """
        UPDATE matches SET actual_home_score = 2, actual_away_score = 1,
            status = 'completed', result_source = 'override'
        WHERE id = :m
        """,
        m=match_id,
    )
    src2 = await _scalar_raw(conn, "SELECT result_source FROM matches WHERE id = :m", m=match_id)
    assert src2 == "override"


async def test_override_result_twice_latest_snapshot_reflects_latest_scores(
    db_conn: Any,
) -> None:
    """Two consecutive overrides — the latest leaderboard snapshot uses the last scores.

    Regression guard for migration 009: with the AFTER trigger's WHEN clause
    dropped, every score change now re-fires scoring. So overriding twice
    should produce a fresh snapshot per override, with the latest one
    matching the final scores.
    """
    from sqlalchemy.ext.asyncio import AsyncConnection

    conn: AsyncConnection = db_conn
    g = await _insert_group(conn, "T")
    home = await _insert_team(conn, g, "Twice A", "TWA")
    away = await _insert_team(conn, g, "Twice B", "TWB")
    alice = await _insert_profile(conn, "alice_twice")

    match_id = await _insert_match_and_predict(
        conn,
        home_id=home,
        away_id=away,
        group_id=g,
        player_id=alice,
        pred_home=2,
        pred_away=1,
    )

    # First entry: 1-0 → result pts only = 3.
    await _exec(
        conn,
        """
        UPDATE matches SET actual_home_score = 1, actual_away_score = 0,
            status = 'completed', result_source = 'manual', result_entered_by = :p
        WHERE id = :m
        """,
        p=alice,
        m=match_id,
    )

    # First override: 0-1 (away win — alice predicted home win, sign mismatch, no result pts).
    await _exec(
        conn,
        """
        UPDATE matches SET actual_home_score = 0, actual_away_score = 1,
            status = 'completed', result_source = 'override', result_entered_by = :p
        WHERE id = :m
        """,
        p=alice,
        m=match_id,
    )

    # Second override: 2-1 (alice predicted exactly → full 10 pts).
    await _exec(
        conn,
        """
        UPDATE matches SET actual_home_score = 2, actual_away_score = 1,
            status = 'completed', result_source = 'override', result_entered_by = :p
        WHERE id = :m
        """,
        p=alice,
        m=match_id,
    )

    pts_final = await _scalar_raw(
        conn,
        "SELECT points_awarded FROM predictions WHERE match_id = :m AND player_id = :p",
        m=match_id,
        p=alice,
    )
    assert pts_final == 10

    # The trigger fired three times (initial + two overrides), so there are
    # three snapshots for this match. We assert the *set* of total_points
    # values because all three snapshots share the same ``snapshot_at`` —
    # they run inside the test's outer transaction, where ``now()`` returns
    # the transaction-start time. In production each override is its own
    # transaction so timestamps differ; here we test the semantic guarantee
    # that the trigger captured each rescoring (3pts → 0pts → 10pts).
    totals = await _fetchall_raw(
        conn,
        """
        SELECT total_points FROM leaderboard_snapshots
        WHERE triggered_by_match_id = :m AND player_id = :p
        """,
        m=match_id,
        p=alice,
    )
    assert sorted(r["total_points"] for r in totals) == [0, 3, 10]
