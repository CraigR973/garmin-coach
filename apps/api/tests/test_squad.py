"""Tests for U14 squad endpoints and golden boot id-based logic."""

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.auth import get_current_player, require_admin
from src.database import get_db
from src.main import app
from src.models.prediction import SpecialPrediction, SpecialPredictionType
from src.models.profile import PlayerRole, Profile
from src.models.squad import SquadPlayer, SquadPosition

# ---------------------------------------------------------------------------
# Helpers
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


def _make_squad_player(
    full_name: str = "Erling Haaland",
    known_as: str = "Haaland",
    position: SquadPosition = SquadPosition.FWD,
) -> MagicMock:
    sp = MagicMock(spec=SquadPlayer)
    sp.id = uuid.uuid4()
    sp.team_id = uuid.uuid4()
    sp.full_name = full_name
    sp.known_as = known_as
    sp.position = position
    sp.shirt_number = 9
    sp.is_active = True
    return sp


def _make_special(
    player_id: uuid.UUID,
    ptype: SpecialPredictionType,
    player_name: str | None = None,
    player_squad_id: uuid.UUID | None = None,
    points: int | None = None,
) -> MagicMock:
    p = MagicMock(spec=SpecialPrediction)
    p.id = uuid.uuid4()
    p.player_id = player_id
    p.prediction_type = ptype
    p.predicted_team_id = None
    p.predicted_player_name = player_name
    p.predicted_player_id = player_squad_id
    p.winner_player_id = None
    p.submitted_at = _now()
    p.points_awarded = points
    p.updated_at = _now()
    return p


def _make_match(locked: bool = False) -> MagicMock:
    m = MagicMock()
    m.id = uuid.uuid4()
    m.kickoff_utc = _now() + (timedelta(hours=-1) if locked else timedelta(hours=1))
    m.deleted_at = None
    return m


def _scalar_one(value: object) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _scalars(items: list) -> MagicMock:
    r = MagicMock()
    r.scalars.return_value.all.return_value = items
    return r


def _stub_db(execute_results: list) -> AsyncMock:
    mock_db = AsyncMock()
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
# U14.1 — squad data coverage
# ---------------------------------------------------------------------------


def test_squad_json_covers_all_48_teams() -> None:
    """All 48 WC 2026 teams have squad entries in the committed JSON."""
    import json
    import pathlib

    data_path = pathlib.Path(__file__).parent.parent / "src" / "data" / "squads_2026.json"
    assert data_path.exists(), "squads_2026.json missing"
    data = json.loads(data_path.read_text())

    by_team: dict[str, int] = {}
    for r in data:
        by_team[r["team_code"]] = by_team.get(r["team_code"], 0) + 1

    assert len(by_team) == 48, f"Expected 48 teams, got {len(by_team)}"
    short = [(t, c) for t, c in by_team.items() if c < 23]
    assert not short, f"Teams with fewer than 23 players: {short}"


def test_squad_json_positions_valid() -> None:
    """All position values are GK/DEF/MID/FWD."""
    import json
    import pathlib

    data = json.loads(
        (pathlib.Path(__file__).parent.parent / "src" / "data" / "squads_2026.json").read_text()
    )
    bad = [r for r in data if r["position"] not in {"GK", "DEF", "MID", "FWD"}]
    assert not bad, f"Invalid positions: {bad[:5]}"


# ---------------------------------------------------------------------------
# U14.3 — search endpoint (mocked DB)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_squad_search_empty_query_returns_empty() -> None:
    mock_db = AsyncMock()
    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/squad/search?q=")
        assert resp.status_code == 200
        assert resp.json() == []
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_squad_search_returns_results() -> None:
    """Search returns list of player dicts when DB has matching rows."""
    player_id = uuid.uuid4()

    row = MagicMock()
    row.id = player_id
    row.full_name = "Erling Haaland"
    row.known_as = "Haaland"
    row.position = "FWD"
    row.shirt_number = 9
    row.team_code = "NOR"
    row.team_name = "Norway"
    row.flag_emoji = "🇳🇴"

    mock_result = MagicMock()
    mock_result.all.return_value = [row]

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/squad/search?q=haaland")
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == 1
        assert results[0]["full_name"] == "Erling Haaland"
        assert results[0]["flag_emoji"] == "🇳🇴"
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# U14.4 — golden boot upsert stores predicted_player_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_put_golden_boot_with_player_id_stores_resolved_name() -> None:
    """PUT /specials/golden_boot with predicted_player_id resolves and stores full_name."""
    player = _make_player()
    squad_player = _make_squad_player(full_name="Erling Haaland")

    match = _make_match(locked=False)
    existing_pred: SpecialPrediction | None = None

    # DB calls:
    # 1. _get_opening_match → match
    # 2. resolve squad player by id
    # 3. fetch existing prediction
    # (then commit + refresh)
    mock_db = _stub_db(
        [
            _scalar_one(match),
            _scalar_one(squad_player),
            _scalar_one(existing_pred),
        ]
    )

    # refresh side effect: set attributes on the newly created pred
    created: list[Any] = []

    def _capture_add(obj: Any) -> None:
        created.append(obj)

    mock_db.add = MagicMock(side_effect=_capture_add)

    async def _refresh(obj: Any) -> None:
        # Populate the object so _to_item can serialise it
        obj.id = uuid.uuid4()
        obj.prediction_type = SpecialPredictionType.golden_boot
        obj.predicted_team_id = None
        obj.predicted_player_id = squad_player.id
        obj.predicted_player_name = "Erling Haaland"
        obj.submitted_at = _now()
        obj.points_awarded = None

    mock_db.refresh = AsyncMock(side_effect=_refresh)

    async with _override(mock_db, player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                "/api/v1/specials/golden_boot",
                json={"predicted_player_id": str(squad_player.id)},
                headers={"Authorization": "Bearer token"},
            )
    assert resp.status_code == 200
    data = resp.json()
    assert data["predicted_player_name"] == "Erling Haaland"
    assert data["predicted_player_id"] == str(squad_player.id)


@pytest.mark.asyncio
async def test_put_golden_boot_without_player_id_rejects() -> None:
    """PUT golden_boot with no predicted_player_id or name → 422."""
    player = _make_player()
    match = _make_match(locked=False)
    mock_db = _stub_db([_scalar_one(match)])

    async with _override(mock_db, player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                "/api/v1/specials/golden_boot",
                json={},
                headers={"Authorization": "Bearer token"},
            )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# U14.5 — award by id credits exactly the right predictions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_award_golden_boot_by_id_credits_correct_predictions() -> None:
    """award_specials with winner_player_id grants points to matching id, not others."""
    with (
        patch("src.routers.specials.notify_special_results_awarded", new_callable=AsyncMock),
        patch("src.routers.specials.recompute_leaderboard_snapshot", new_callable=AsyncMock),
    ):
        admin = _make_player(role=PlayerRole.admin)
        winner_squad_id = uuid.uuid4()
        other_squad_id = uuid.uuid4()

        winner_player = _make_squad_player()
        winner_player.id = winner_squad_id

        # Two predictions: one picked the winner, one didn't
        pred_correct = _make_special(
            uuid.uuid4(),
            SpecialPredictionType.golden_boot,
            player_squad_id=winner_squad_id,
        )
        pred_wrong = _make_special(
            uuid.uuid4(),
            SpecialPredictionType.golden_boot,
            player_squad_id=other_squad_id,
        )

        mock_db = _stub_db(
            [
                _scalar_one(winner_player),  # verify winner exists
                _scalars([pred_correct, pred_wrong]),  # fetch all preds
            ]
        )

        async with _override(mock_db, admin):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/v1/admin/specials/award",
                    json={
                        "prediction_type": "golden_boot",
                        "winner_player_id": str(winner_squad_id),
                    },
                    headers={"Authorization": "Bearer token"},
                )

        assert resp.status_code == 200
        body = resp.json()
        assert body["awarded_count"] == 1
        assert body["points_each"] == 15

        # Correct pred gets 15, wrong gets 0
        assert pred_correct.points_awarded == 15
        assert pred_wrong.points_awarded == 0


@pytest.mark.asyncio
async def test_award_golden_boot_requires_winner_player_id() -> None:
    """Omitting winner_player_id for golden_boot → 422."""
    with (
        patch("src.routers.specials.notify_special_results_awarded", new_callable=AsyncMock),
        patch("src.routers.specials.recompute_leaderboard_snapshot", new_callable=AsyncMock),
    ):
        admin = _make_player(role=PlayerRole.admin)
        mock_db = _stub_db([])

        async with _override(mock_db, admin):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/v1/admin/specials/award",
                    json={"prediction_type": "golden_boot"},
                    headers={"Authorization": "Bearer token"},
                )

        assert resp.status_code == 422
