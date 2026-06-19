"""Tests for special predictions endpoints."""

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

from src.auth import get_current_player, require_admin
from src.database import get_db
from src.main import app
from src.models.prediction import SpecialPrediction, SpecialPredictionType
from src.models.profile import PlayerRole, Profile


@pytest.fixture(autouse=True)
def _patch_external_collaborators() -> None:
    """Patch out the notify hook and the leaderboard helper.

    The helper is bypassed because the mock-based ``award_specials`` tests
    use ``_stub_db`` which has a finite ``side_effect`` list — the helper's
    extra ``execute(text(...))`` call would otherwise exhaust it. The
    ``test_award_specials_calls_recompute_leaderboard_snapshot`` test
    re-patches the helper itself to assert it's invoked.
    """
    with (
        patch("src.routers.specials.notify_special_results_awarded", new_callable=AsyncMock),
        patch("src.routers.specials.recompute_leaderboard_snapshot", new_callable=AsyncMock),
    ):
        yield


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _make_player(role: PlayerRole = PlayerRole.player) -> Profile:
    p = MagicMock(spec=Profile)
    p.avatar_url = None  # U23: prevent MagicMock default from failing Pydantic
    p.id = uuid.uuid4()
    p.display_name = "TestPlayer"
    p.role = role
    p.deleted_at = None
    return p


def _make_admin() -> Profile:
    return _make_player(role=PlayerRole.admin)


def _make_match(locked: bool = False) -> MagicMock:
    m = MagicMock()
    m.id = uuid.uuid4()
    m.kickoff_utc = _now() + (timedelta(hours=-1) if locked else timedelta(hours=1))
    m.deleted_at = None
    return m


def _make_special(
    player_id: uuid.UUID,
    ptype: SpecialPredictionType,
    team_id: uuid.UUID | None = None,
    player_name: str | None = None,
    points: int | None = None,
) -> SpecialPrediction:
    p = MagicMock(spec=SpecialPrediction)
    p.id = uuid.uuid4()
    p.player_id = player_id
    p.prediction_type = ptype
    p.predicted_team_id = team_id
    p.predicted_player_name = player_name
    p.predicted_player_id = None
    p.winner_player_id = None
    p.submitted_at = _now()
    p.points_awarded = points
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


def _rows(pairs: list) -> MagicMock:
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
    app.dependency_overrides[require_admin] = lambda: player
    try:
        yield
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /api/v1/specials
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_my_specials_empty() -> None:
    """Returns all 6 types with nulls when no predictions submitted yet."""
    player = _make_player()
    opening = _make_match(locked=False)
    db = _stub_db([_scalar_one(opening), _scalars([])])

    async with _override(db, player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/specials", headers={"Authorization": "Bearer x"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["is_locked"] is False
    assert data["lock_at"] is not None
    assert len(data["predictions"]) == 6
    assert all(p["submitted_at"] is None for p in data["predictions"])


@pytest.mark.asyncio
async def test_get_my_specials_with_existing() -> None:
    """Returns submitted predictions correctly."""
    player = _make_player()
    team_id = uuid.uuid4()
    opening = _make_match(locked=False)
    pred = _make_special(player.id, SpecialPredictionType.tournament_winner, team_id=team_id)
    db = _stub_db([_scalar_one(opening), _scalars([pred])])

    async with _override(db, player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/specials", headers={"Authorization": "Bearer x"})

    assert resp.status_code == 200
    data = resp.json()
    tw = next(p for p in data["predictions"] if p["prediction_type"] == "tournament_winner")
    assert tw["predicted_team_id"] == str(team_id)
    assert tw["submitted_at"] is not None


@pytest.mark.asyncio
async def test_get_my_specials_locked() -> None:
    """is_locked is True when past opening match kickoff."""
    player = _make_player()
    opening = _make_match(locked=True)
    db = _stub_db([_scalar_one(opening), _scalars([])])

    async with _override(db, player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/specials", headers={"Authorization": "Bearer x"})

    assert resp.status_code == 200
    assert resp.json()["is_locked"] is True


# ---------------------------------------------------------------------------
# PUT /api/v1/specials/{type}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_put_special_tournament_winner_creates() -> None:
    """Creates a new tournament_winner special prediction."""
    player = _make_player()
    team_id = uuid.uuid4()
    opening = _make_match(locked=False)
    pred = _make_special(player.id, SpecialPredictionType.tournament_winner, team_id=team_id)
    db = _stub_db([_scalar_one(opening), _scalar_one(None)])
    db.refresh = AsyncMock(side_effect=lambda obj: _patch_special(obj, pred))

    async with _override(db, player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                "/api/v1/specials/tournament_winner",
                json={"predicted_team_id": str(team_id)},
                headers={"Authorization": "Bearer x"},
            )

    assert resp.status_code == 200
    assert resp.json()["predicted_team_id"] == str(team_id)
    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_put_special_golden_boot_creates() -> None:
    """Creates a new golden_boot special prediction (free text)."""
    player = _make_player()
    opening = _make_match(locked=False)
    pred = _make_special(player.id, SpecialPredictionType.golden_boot, player_name="Kylian Mbappé")
    db = _stub_db([_scalar_one(opening), _scalar_one(None)])
    db.refresh = AsyncMock(side_effect=lambda obj: _patch_special(obj, pred))

    async with _override(db, player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                "/api/v1/specials/golden_boot",
                json={"predicted_player_name": "Kylian Mbappé"},
                headers={"Authorization": "Bearer x"},
            )

    assert resp.status_code == 200
    assert resp.json()["predicted_player_name"] == "Kylian Mbappé"


@pytest.mark.asyncio
async def test_put_special_locked_returns_409() -> None:
    """Returns 409 when tournament has started."""
    player = _make_player()
    opening = _make_match(locked=True)
    team_id = uuid.uuid4()
    db = _stub_db([_scalar_one(opening)])

    async with _override(db, player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                "/api/v1/specials/tournament_winner",
                json={"predicted_team_id": str(team_id)},
                headers={"Authorization": "Bearer x"},
            )

    assert resp.status_code == 409
    assert resp.json()["detail"] == "PREDICTION_LOCKED"


@pytest.mark.asyncio
async def test_put_special_golden_boot_missing_name_returns_422() -> None:
    """Returns 422 if predicted_player_name missing for golden_boot."""
    player = _make_player()
    opening = _make_match(locked=False)
    db = _stub_db([_scalar_one(opening)])

    async with _override(db, player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                "/api/v1/specials/golden_boot",
                json={},
                headers={"Authorization": "Bearer x"},
            )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_put_special_team_type_missing_team_returns_422() -> None:
    """Returns 422 if predicted_team_id missing for tournament_winner."""
    player = _make_player()
    opening = _make_match(locked=False)
    db = _stub_db([_scalar_one(opening)])

    async with _override(db, player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                "/api/v1/specials/tournament_winner",
                json={},
                headers={"Authorization": "Bearer x"},
            )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_put_special_updates_existing() -> None:
    """Updates an existing prediction."""
    player = _make_player()
    team_id = uuid.uuid4()
    new_team_id = uuid.uuid4()
    opening = _make_match(locked=False)
    existing = _make_special(player.id, SpecialPredictionType.tournament_winner, team_id=team_id)
    updated = _make_special(player.id, SpecialPredictionType.tournament_winner, team_id=new_team_id)
    db = _stub_db([_scalar_one(opening), _scalar_one(existing)])
    db.refresh = AsyncMock(side_effect=lambda obj: _patch_special(obj, updated))

    async with _override(db, player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                "/api/v1/specials/tournament_winner",
                json={"predicted_team_id": str(new_team_id)},
                headers={"Authorization": "Bearer x"},
            )

    assert resp.status_code == 200
    assert resp.json()["predicted_team_id"] == str(new_team_id)
    db.add.assert_not_called()


# ---------------------------------------------------------------------------
# GET /api/v1/specials/all
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_all_specials_pre_lock_returns_403() -> None:
    """Returns 403 before tournament starts."""
    player = _make_player()
    opening = _make_match(locked=False)
    db = _stub_db([_scalar_one(opening)])

    async with _override(db, player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/specials/all", headers={"Authorization": "Bearer x"})

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_all_specials_post_lock() -> None:
    """Returns all players' predictions after tournament starts."""
    player = _make_player()
    other_id = uuid.uuid4()
    other_profile = MagicMock(spec=Profile)
    other_profile.avatar_url = None  # U23: prevent MagicMock default from failing Pydantic
    other_profile.id = other_id
    other_profile.display_name = "OtherPlayer"
    other_profile.deleted_at = None

    opening = _make_match(locked=True)
    pred = _make_special(other_id, SpecialPredictionType.tournament_winner, team_id=uuid.uuid4())
    db = _stub_db([_scalar_one(opening), _rows([(pred, other_profile)])])

    with patch(
        "src.routers.specials.shared_league_player_ids",
        return_value=frozenset({player.id, other_id}),
    ):
        async with _override(db, player):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    "/api/v1/specials/all", headers={"Authorization": "Bearer x"}
                )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["player_name"] == "OtherPlayer"
    assert len(data[0]["predictions"]) == 1


# ---------------------------------------------------------------------------
# POST /api/v1/admin/specials/award
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_award_specials_tournament_winner() -> None:
    """Awards 20 pts to correct tournament winner predictions."""
    admin = _make_admin()
    team_id = uuid.uuid4()
    wrong_team_id = uuid.uuid4()

    correct_pred = _make_special(
        uuid.uuid4(), SpecialPredictionType.tournament_winner, team_id=team_id
    )
    correct_pred.points_awarded = None
    wrong_pred = _make_special(
        uuid.uuid4(), SpecialPredictionType.tournament_winner, team_id=wrong_team_id
    )
    wrong_pred.points_awarded = None

    db = _stub_db([_scalars([correct_pred, wrong_pred])])

    async with _override(db, admin):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/admin/specials/award",
                json={
                    "prediction_type": "tournament_winner",
                    "winner_team_id": str(team_id),
                },
                headers={"Authorization": "Bearer x"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["prediction_type"] == "tournament_winner"
    assert data["awarded_count"] == 1
    assert data["points_each"] == 20
    assert correct_pred.points_awarded == 20
    assert wrong_pred.points_awarded == 0


@pytest.mark.asyncio
async def test_award_specials_golden_boot_by_id() -> None:
    """Awards 15 pts for golden boot using winner_player_id (id-match, U14.5)."""
    from unittest.mock import MagicMock

    from src.models.squad import SquadPlayer

    admin = _make_admin()
    winner_id = uuid.uuid4()

    winner_squad = MagicMock(spec=SquadPlayer)
    winner_squad.id = winner_id
    winner_squad.full_name = "Kylian Mbappé"

    correct_pred = _make_special(
        uuid.uuid4(), SpecialPredictionType.golden_boot, player_name="Kylian Mbappé"
    )
    correct_pred.predicted_player_id = winner_id
    correct_pred.winner_player_id = None
    correct_pred.points_awarded = None

    wrong_pred = _make_special(
        uuid.uuid4(), SpecialPredictionType.golden_boot, player_name="Erling Haaland"
    )
    wrong_pred.predicted_player_id = uuid.uuid4()
    wrong_pred.winner_player_id = None
    wrong_pred.points_awarded = None

    db = _stub_db([_scalar_one(winner_squad), _scalars([correct_pred, wrong_pred])])

    async with _override(db, admin):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/admin/specials/award",
                json={
                    "prediction_type": "golden_boot",
                    "winner_player_id": str(winner_id),
                },
                headers={"Authorization": "Bearer x"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["awarded_count"] == 1
    assert data["points_each"] == 15
    assert correct_pred.points_awarded == 15
    assert wrong_pred.points_awarded == 0


@pytest.mark.asyncio
async def test_award_specials_golden_boot_missing_player_id_returns_422() -> None:
    """Returns 422 if winner_player_id missing for golden_boot award (U14.5)."""
    admin = _make_admin()
    db = _stub_db([])

    async with _override(db, admin):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/admin/specials/award",
                json={"prediction_type": "golden_boot"},
                headers={"Authorization": "Bearer x"},
            )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_award_specials_top_scoring_team() -> None:
    """Awards 10 pts for top_scoring_team."""
    admin = _make_admin()
    team_id = uuid.uuid4()
    pred = _make_special(uuid.uuid4(), SpecialPredictionType.top_scoring_team, team_id=team_id)
    pred.points_awarded = None

    db = _stub_db([_scalars([pred])])

    async with _override(db, admin):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/admin/specials/award",
                json={
                    "prediction_type": "top_scoring_team",
                    "winner_team_id": str(team_id),
                },
                headers={"Authorization": "Bearer x"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["points_each"] == 10
    assert data["awarded_count"] == 1
    assert pred.points_awarded == 10


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _patch_special(obj: object, template: SpecialPrediction) -> None:
    for attr in (
        "id",
        "player_id",
        "prediction_type",
        "predicted_team_id",
        "predicted_player_name",
        "submitted_at",
        "points_awarded",
        "updated_at",
    ):
        setattr(obj, attr, getattr(template, attr))


# ---------------------------------------------------------------------------
# 12.2 — new player special types use the generalised player path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ptype, expected_pts",
    [
        (SpecialPredictionType.player_of_tournament, 15),
        (SpecialPredictionType.young_player_of_tournament, 10),
        (SpecialPredictionType.golden_glove, 10),
    ],
)
async def test_new_player_specials_upsert(ptype: SpecialPredictionType, expected_pts: int) -> None:
    """player_of_tournament, young_player_of_tournament, golden_glove use the player path."""
    from src.models.squad import SquadPlayer

    player = _make_player()
    squad_player = MagicMock(spec=SquadPlayer)
    squad_player.id = uuid.uuid4()
    squad_player.full_name = "Test Player"
    opening = _make_match(locked=False)
    pred = _make_special(player.id, ptype, player_name="Test Player")
    pred.predicted_player_id = squad_player.id
    db = _stub_db([_scalar_one(opening), _scalar_one(squad_player), _scalar_one(None)])
    db.refresh = AsyncMock(side_effect=lambda obj: _patch_special(obj, pred))

    async with _override(db, player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                f"/api/v1/specials/{ptype}",
                json={"predicted_player_id": str(squad_player.id)},
                headers={"Authorization": "Bearer x"},
            )

    assert resp.status_code == 200
    assert resp.json()["prediction_type"] == ptype


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ptype, expected_pts",
    [
        (SpecialPredictionType.player_of_tournament, 15),
        (SpecialPredictionType.young_player_of_tournament, 10),
        (SpecialPredictionType.golden_glove, 10),
    ],
)
async def test_new_player_specials_award(ptype: SpecialPredictionType, expected_pts: int) -> None:
    """Award endpoint grants correct points for the three new player specials."""
    from src.models.squad import SquadPlayer

    admin = _make_admin()
    winner_id = uuid.uuid4()
    winner_squad = MagicMock(spec=SquadPlayer)
    winner_squad.id = winner_id

    correct_pred = _make_special(uuid.uuid4(), ptype, player_name="Test Player")
    correct_pred.predicted_player_id = winner_id
    correct_pred.winner_player_id = None
    correct_pred.points_awarded = None

    wrong_pred = _make_special(uuid.uuid4(), ptype, player_name="Other Player")
    wrong_pred.predicted_player_id = uuid.uuid4()
    wrong_pred.winner_player_id = None
    wrong_pred.points_awarded = None

    db = _stub_db([_scalar_one(winner_squad), _scalars([correct_pred, wrong_pred])])

    async with _override(db, admin):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/admin/specials/award",
                json={"prediction_type": ptype, "winner_player_id": str(winner_id)},
                headers={"Authorization": "Bearer x"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["awarded_count"] == 1
    assert data["points_each"] == expected_pts
    assert correct_pred.points_awarded == expected_pts
    assert wrong_pred.points_awarded == 0


# ---------------------------------------------------------------------------
# R2.4 — award_specials triggers a leaderboard snapshot recompute
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_award_specials_calls_recompute_leaderboard_snapshot() -> None:
    """The award route must invoke recompute_leaderboard_snapshot before commit.

    Without this, the final standings stay stuck on the last match-result
    snapshot and special points never propagate to the leaderboard.
    """
    admin = _make_admin()
    team_id = uuid.uuid4()
    pred = _make_special(uuid.uuid4(), SpecialPredictionType.tournament_winner, team_id=team_id)
    pred.points_awarded = None
    db = _stub_db([_scalars([pred])])

    with patch(
        "src.routers.specials.recompute_leaderboard_snapshot", new_callable=AsyncMock
    ) as mock_helper:
        async with _override(db, admin):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/admin/specials/award",
                    json={
                        "prediction_type": "tournament_winner",
                        "winner_team_id": str(team_id),
                    },
                    headers={"Authorization": "Bearer x"},
                )

    assert resp.status_code == 200
    mock_helper.assert_awaited_once()
    args, kwargs = mock_helper.await_args
    # First positional is the session; triggered_by_match_id is None for specials.
    assert kwargs.get("triggered_by_match_id") is None


# ---------------------------------------------------------------------------
# R2.5 — integration: snapshot reflects awarded special points
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
    # helper exercised by these tests needs a membership row to write to.
    from tests.conftest import ensure_default_league_membership

    await ensure_default_league_membership(conn, profile_id)
    return profile_id


async def test_award_specials_snapshot_has_correct_points(db_conn: AsyncConnection) -> None:
    """After recompute, snapshot per player has correct special_points and total_points.

    Mirrors the runtime flow: a completed match awarded match points, then
    award_specials writes special_predictions.points_awarded, then the helper
    recomputes the snapshot. The snapshot must reflect both.
    """
    from src.services.leaderboard import recompute_leaderboard_snapshot

    g = await _insert_group_raw(db_conn, "Z")
    home = await _insert_team_raw(db_conn, g, "Zalpha", "ZAA")
    away = await _insert_team_raw(db_conn, g, "Zbeta", "ZAB")
    winner_team = await _insert_team_raw(db_conn, g, "Zgamma", "ZAG")
    alice = await _insert_profile_raw(db_conn, "alice_specials_snap")
    bob = await _insert_profile_raw(db_conn, "bob_specials_snap")

    # A completed match: alice predicts 2-1 exact (10 pts), bob predicts 0-0 (0 pts).
    match_id = await _scalar_raw(
        db_conn,
        """
        INSERT INTO matches (id, stage, group_id, match_number, home_team_id,
            away_team_id, kickoff_utc, status)
        VALUES (gen_random_uuid(), 'group', :g, 950, :h, :a, '2026-06-12 18:00:00', 'locked')
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
        INSERT INTO predictions (id, player_id, match_id, predicted_home, predicted_away)
        VALUES (gen_random_uuid(), :p, :m, 0, 0)
        """,
        p=bob,
        m=match_id,
    )
    # Enter result — the trigger fires and writes initial snapshot rows.
    await _exec_raw(
        db_conn,
        """
        UPDATE matches SET actual_home_score = 2, actual_away_score = 1,
            status = 'completed', result_source = 'manual'
        WHERE id = :m
        """,
        m=match_id,
    )

    # Now mimic award_specials: write 20 pts to alice's tournament_winner pred.
    await _exec_raw(
        db_conn,
        """
        INSERT INTO special_predictions (
            id, player_id, prediction_type, predicted_team_id, points_awarded
        )
        VALUES (gen_random_uuid(), :p, 'tournament_winner', :t, 20)
        """,
        p=alice,
        t=winner_team,
    )
    await _exec_raw(
        db_conn,
        """
        INSERT INTO special_predictions (
            id, player_id, prediction_type, predicted_team_id, points_awarded
        )
        VALUES (gen_random_uuid(), :p, 'tournament_winner', :t, 0)
        """,
        p=bob,
        t=winner_team,
    )

    # Run the helper via an AsyncSession bound to the same connection.
    session = AsyncSession(bind=db_conn, expire_on_commit=False)
    try:
        await recompute_leaderboard_snapshot(session, triggered_by_match_id=None)
    finally:
        await session.close()

    rows = await _fetchall_raw(
        db_conn,
        """
        SELECT DISTINCT ON (s.player_id)
            p.display_name, s.match_points, s.special_points,
            s.total_points, s.triggered_by_match_id
        FROM leaderboard_snapshots s JOIN profiles p ON p.id = s.player_id
        WHERE s.player_id IN (:a, :b)
          -- Read the post-recompute snapshot (triggered_by_match_id IS NULL),
          -- not the trigger's match snapshot. Both share snapshot_at (one
          -- transaction_timestamp() per db_conn txn), so ordering on snapshot_at
          -- alone ties nondeterministically — the recompute filter is the
          -- deterministic discriminator.
          AND s.triggered_by_match_id IS NULL
        ORDER BY s.player_id, s.snapshot_at DESC
        """,
        a=alice,
        b=bob,
    )
    by_name = {r["display_name"]: r for r in rows}
    # alice: 10 match + 20 special = 30
    assert by_name["alice_specials_snap"]["match_points"] == 10
    assert by_name["alice_specials_snap"]["special_points"] == 20
    assert by_name["alice_specials_snap"]["total_points"] == 30
    assert by_name["alice_specials_snap"]["triggered_by_match_id"] is None
    # bob: 0 match + 0 special = 0
    assert by_name["bob_specials_snap"]["match_points"] == 0
    assert by_name["bob_specials_snap"]["special_points"] == 0
    assert by_name["bob_specials_snap"]["total_points"] == 0
