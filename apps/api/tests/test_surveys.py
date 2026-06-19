"""Tests for the in-app survey endpoints (/api/v1/surveys).

Mock-based (no DB), mirroring test_me_home: get_current_player + get_db are
overridden and db.execute side effects are scripted per query.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from src.auth import get_current_player
from src.database import get_db
from src.main import app
from src.models.profile import Profile

KEY = "week1_pulse"


def _player(pid: uuid.UUID | None = None) -> MagicMock:
    p = MagicMock(spec=Profile)
    p.id = pid or uuid.uuid4()
    return p


def _db_with(mock_db: AsyncMock):  # type: ignore[no-untyped-def]
    async def _override():  # type: ignore[no-untyped-def]
        yield mock_db

    return _override


def _scalar(value: object):
    """Mock result for .scalar_one_or_none()."""
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _scalars(rows: list):  # type: ignore[no-untyped-def]
    """Mock result for .scalars().all()."""
    r = MagicMock()
    r.scalars.return_value.all.return_value = rows
    return r


def _mock_db(side_effects: list) -> AsyncMock:  # type: ignore[no-untyped-def]
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=side_effects)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _valid_answers() -> dict:
    return {
        "q2_overall": 4,
        "q3_frequency": "daily",
        "q4_notifications": "about_right",
        "q5_missed_deadline": "no",
        "q6_biggest_annoyance": "leaderboard",
        "q7_open": "Love it but the table is long",
        "q9_scotland": "0, gloriously",
    }


async def _request(
    method: str,
    path: str,
    mock_db: AsyncMock,
    player: MagicMock,
    json: dict | None = None,
):  # type: ignore[no-untyped-def]
    app.dependency_overrides[get_current_player] = lambda: player
    app.dependency_overrides[get_db] = _db_with(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            return await c.request(method, path, json=json)
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_incomplete() -> None:
    db = _mock_db([_scalar(None)])
    resp = await _request("GET", f"/api/v1/surveys/{KEY}/status", db, _player())
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"completed": False}


@pytest.mark.asyncio
async def test_status_completed() -> None:
    db = _mock_db([_scalar(uuid.uuid4())])
    resp = await _request("GET", f"/api/v1/surveys/{KEY}/status", db, _player())
    assert resp.json() == {"completed": True}


@pytest.mark.asyncio
async def test_status_unknown_survey_404() -> None:
    db = _mock_db([])
    resp = await _request("GET", "/api/v1/surveys/nope/status", db, _player())
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_records_response_and_completion() -> None:
    pid = uuid.uuid4()
    league_id = uuid.uuid4()
    db = _mock_db(
        [
            _scalar(None),  # not already completed
            _scalars([league_id]),  # caller's active leagues
        ]
    )
    resp = await _request(
        "POST",
        f"/api/v1/surveys/{KEY}/response",
        db,
        _player(pid),
        json={"answers": _valid_answers(), "contact_ok": False},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"completed": True}
    db.commit.assert_awaited_once()
    # Two rows added: the de-identified response, then the completion gate.
    assert db.add.call_count == 2
    response_row = db.add.call_args_list[0].args[0]
    assert response_row.survey_key == KEY
    assert response_row.league_ids == [str(league_id)]
    assert response_row.contact_player_id is None  # anonymous by default
    assert response_row.answers["q2_overall"] == 4
    completion_row = db.add.call_args_list[1].args[0]
    assert completion_row.player_id == pid


@pytest.mark.asyncio
async def test_submit_contact_opt_in_attaches_identity() -> None:
    pid = uuid.uuid4()
    db = _mock_db([_scalar(None), _scalars([])])
    await _request(
        "POST",
        f"/api/v1/surveys/{KEY}/response",
        db,
        _player(pid),
        json={"answers": _valid_answers(), "contact_ok": True},
    )
    response_row = db.add.call_args_list[0].args[0]
    assert response_row.contact_player_id == pid
    assert response_row.league_ids == []


@pytest.mark.asyncio
async def test_submit_idempotent_when_already_completed() -> None:
    db = _mock_db([_scalar(uuid.uuid4())])  # already completed
    resp = await _request(
        "POST",
        f"/api/v1/surveys/{KEY}/response",
        db,
        _player(),
        json={"answers": _valid_answers()},
    )
    assert resp.status_code == 200
    assert resp.json() == {"completed": True}
    db.add.assert_not_called()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_submit_unknown_survey_404() -> None:
    db = _mock_db([])
    resp = await _request(
        "POST",
        "/api/v1/surveys/nope/response",
        db,
        _player(),
        json={"answers": _valid_answers()},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_submit_rejects_invalid_rating() -> None:
    db = _mock_db([])
    answers = _valid_answers()
    answers["q2_overall"] = 6  # out of 1..5
    resp = await _request(
        "POST",
        f"/api/v1/surveys/{KEY}/response",
        db,
        _player(),
        json={"answers": answers},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_submit_rejects_unknown_choice() -> None:
    db = _mock_db([])
    answers = _valid_answers()
    answers["q6_biggest_annoyance"] = "weather"
    resp = await _request(
        "POST",
        f"/api/v1/surveys/{KEY}/response",
        db,
        _player(),
        json={"answers": answers},
    )
    assert resp.status_code == 422
