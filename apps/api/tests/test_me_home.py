"""Tests for GET /api/v1/me/home (U17.1).

Mock-based tests verify:
- todo block: specials_submitted, specials_lock_at, upcoming_unpredicted, next_match
- rollup block: matchday grouping, points sum, match details
- Edge cases: pre-tournament empty state, locked match exclusion semantics,
  specials locked clears lock_at, rollup null when no scored predictions
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from src.auth import get_current_player
from src.database import get_db
from src.main import app
from src.models.profile import Profile

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _player() -> MagicMock:
    p = MagicMock(spec=Profile)
    p.avatar_url = None  # U23: prevent MagicMock default from failing Pydantic
    p.id = uuid.uuid4()
    p.display_name = "HomePlayer"
    return p


def _db_with(mock_db: AsyncMock):  # type: ignore[no-untyped-def]
    async def _override():  # type: ignore[no-untyped-def]
        yield mock_db

    return _override


def _row(row: object):
    """Mock result for .scalar_one_or_none()"""
    r = MagicMock()
    r.scalar_one_or_none.return_value = row
    return r


def _count(n: int):
    """Mock result for .scalar_one()"""
    r = MagicMock()
    r.scalar_one.return_value = n
    return r


def _scalars(rows: list):  # type: ignore[no-untyped-def]
    """Mock result for .scalars().all()"""
    r = MagicMock()
    r.scalars.return_value.all.return_value = rows
    return r


def _all(rows: list):  # type: ignore[no-untyped-def]
    """Mock result for .all()"""
    r = MagicMock()
    r.all.return_value = rows
    return r


def _make_match(
    *,
    hours_offset: float = 1.0,
    home_team_id: uuid.UUID | None = None,
    away_team_id: uuid.UUID | None = None,
    home_placeholder: str | None = "Home FC",
    away_placeholder: str | None = "Away FC",
    actual_home: int | None = None,
    actual_away: int | None = None,
) -> MagicMock:
    m = MagicMock()
    m.id = uuid.uuid4()
    m.kickoff_utc = _now() + timedelta(hours=hours_offset)
    m.home_team_id = home_team_id
    m.away_team_id = away_team_id
    m.home_team_placeholder = home_placeholder
    m.away_team_placeholder = away_placeholder
    m.actual_home_score = actual_home
    m.actual_away_score = actual_away
    m.deleted_at = None
    return m


def _make_prediction(
    *,
    match: MagicMock,
    predicted_home: int | None = 1,
    predicted_away: int | None = 0,
    points_awarded: int | None = 5,
    points_breakdown: dict | None = None,
) -> MagicMock:
    p = MagicMock()
    p.id = uuid.uuid4()
    p.match_id = match.id
    p.predicted_home = predicted_home
    p.predicted_away = predicted_away
    p.points_awarded = points_awarded
    p.points_breakdown = points_breakdown
    p.deleted_at = None
    return p


async def _call_home(mock_db: AsyncMock) -> dict:  # type: ignore[no-untyped-def]
    app.dependency_overrides[get_current_player] = _player
    app.dependency_overrides[get_db] = _db_with(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/v1/me/home")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200, resp.text
    return resp.json()


def _mock_db(side_effects: list) -> AsyncMock:  # type: ignore[no-untyped-def]
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=side_effects)
    return db


# ---------------------------------------------------------------------------
# Pre-tournament empty state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_home_pre_tournament_empty() -> None:
    """No opening match, no matches, no specials → empty todo + null rollup."""
    db = _mock_db(
        [
            _row(None),  # opening match → None
            _count(0),  # specials count → 0
            _count(0),  # upcoming_unpredicted → 0
            _row(None),  # next_match → None
            _all([]),  # rollup rows → empty
        ]
    )

    data = await _call_home(db)

    assert data["rollup"] is None
    todo = data["todo"]
    assert todo["specials_submitted"] is False
    assert todo["specials_lock_at"] is None
    assert todo["upcoming_unpredicted"] == 0
    assert todo["next_match"] is None


# ---------------------------------------------------------------------------
# specials_submitted flag
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_home_specials_submitted_false() -> None:
    """No specials predictions → specials_submitted=false."""
    db = _mock_db(
        [
            _row(None),
            _count(0),
            _count(0),
            _row(None),
            _all([]),
        ]
    )
    data = await _call_home(db)
    assert data["todo"]["specials_submitted"] is False


@pytest.mark.asyncio
async def test_home_specials_submitted_true() -> None:
    """Player has submitted specials → specials_submitted=true."""
    future_match = _make_match(hours_offset=48.0)
    db = _mock_db(
        [
            _row(future_match),
            _count(3),  # 3 specials submitted
            _count(0),  # opening_match_predicted
            _count(0),  # upcoming_unpredicted
            _row(None),
            _all([]),
        ]
    )
    data = await _call_home(db)
    assert data["todo"]["specials_submitted"] is True


# ---------------------------------------------------------------------------
# specials_lock_at cleared when specials are locked
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_home_specials_lock_at_present_when_future() -> None:
    """Opening match in future → specials_lock_at carries the timestamp."""
    future_match = _make_match(hours_offset=24.0)
    db = _mock_db(
        [
            _row(future_match),
            _count(0),  # specials
            _count(0),  # opening_match_predicted
            _count(0),  # upcoming_unpredicted
            _row(None),
            _all([]),
        ]
    )
    data = await _call_home(db)
    assert data["todo"]["specials_lock_at"] is not None


@pytest.mark.asyncio
async def test_home_specials_lock_at_none_when_locked() -> None:
    """Opening match in the past → specials are locked; specials_lock_at=null."""
    past_match = _make_match(hours_offset=-2.0)
    db = _mock_db(
        [
            _row(past_match),
            _count(0),  # specials
            _count(0),  # opening_match_predicted
            _count(0),  # upcoming_unpredicted
            _row(None),
            _all([]),
        ]
    )
    data = await _call_home(db)
    assert data["todo"]["specials_lock_at"] is None


# ---------------------------------------------------------------------------
# next_match todo
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_home_next_match_unpredicted() -> None:
    """Next match exists and has no prediction → next_match.predicted=false."""
    opening = _make_match(hours_offset=48.0)
    next_match = _make_match(hours_offset=24.0)
    db = _mock_db(
        [
            _row(opening),
            _count(0),  # specials
            _count(0),  # opening_match_predicted
            _count(1),  # upcoming_unpredicted (this match)
            _row(next_match),  # next_match
            # next_match has no team_ids → skip team query
            _count(0),  # has_pred = 0 (not predicted)
            _all([]),  # rollup
        ]
    )
    data = await _call_home(db)
    assert data["todo"]["next_match"] is not None
    assert data["todo"]["next_match"]["predicted"] is False
    assert data["todo"]["upcoming_unpredicted"] == 1


@pytest.mark.asyncio
async def test_home_next_match_predicted() -> None:
    """Next match already predicted → predicted=true."""
    opening = _make_match(hours_offset=48.0)
    next_match = _make_match(hours_offset=24.0)
    db = _mock_db(
        [
            _row(opening),
            _count(0),  # specials
            _count(0),  # opening_match_predicted
            _count(0),  # all upcoming predicted
            _row(next_match),
            _count(1),  # has_pred = 1
            _all([]),
        ]
    )
    data = await _call_home(db)
    assert data["todo"]["next_match"] is not None
    assert data["todo"]["next_match"]["predicted"] is True
    assert data["todo"]["upcoming_unpredicted"] == 0


@pytest.mark.asyncio
async def test_home_next_match_uses_placeholder_labels() -> None:
    """next_match with no team ids → labels come from placeholders."""
    opening = _make_match(hours_offset=48.0)
    next_match = _make_match(
        hours_offset=24.0,
        home_team_id=None,
        away_team_id=None,
        home_placeholder="🇧🇷 Brazil (placeholder)",
        away_placeholder="TBD",
    )
    db = _mock_db(
        [
            _row(opening),
            _count(0),  # specials
            _count(0),  # opening_match_predicted
            _count(1),  # upcoming_unpredicted
            _row(next_match),
            _count(0),  # has_pred
            _all([]),
        ]
    )
    data = await _call_home(db)
    nm = data["todo"]["next_match"]
    assert nm["home_label"] == "🇧🇷 Brazil (placeholder)"
    assert nm["away_label"] == "TBD"


# ---------------------------------------------------------------------------
# Rollup block
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_home_rollup_null_when_no_scored_predictions() -> None:
    """No scored predictions → rollup is null."""
    db = _mock_db(
        [
            _row(None),
            _count(0),
            _count(0),
            _row(None),
            _all([]),
        ]
    )
    data = await _call_home(db)
    assert data["rollup"] is None


@pytest.mark.asyncio
async def test_home_rollup_groups_matchday_and_sums_points() -> None:
    """Two predictions from the same matchday → correct rollup block."""
    # Completed matches in the past
    m1 = _make_match(hours_offset=-24.0, actual_home=2, actual_away=1)
    m2 = _make_match(hours_offset=-23.0, actual_home=0, actual_away=0)
    # Override kickoff to same UTC date
    target_date = datetime(2026, 6, 1, 15, 0, 0)
    m1.kickoff_utc = target_date
    m2.kickoff_utc = target_date.replace(hour=18)

    p1 = _make_prediction(match=m1, predicted_home=2, predicted_away=1, points_awarded=7)
    p2 = _make_prediction(match=m2, predicted_home=1, predicted_away=0, points_awarded=3)

    db = _mock_db(
        [
            _row(None),  # no opening match
            _count(0),  # no specials
            _count(0),  # no upcoming
            _row(None),  # no next_match
            _all([(p1, m1), (p2, m2)]),  # rollup rows (no team_ids so no team query)
        ]
    )
    data = await _call_home(db)

    rollup = data["rollup"]
    assert rollup is not None
    assert rollup["matchday"] == "2026-06-01"
    assert rollup["points_gained"] == 10
    assert rollup["match_count"] == 2
    assert len(rollup["matches"]) == 2


@pytest.mark.asyncio
async def test_home_rollup_match_details() -> None:
    """Rollup match item includes scores, predicted scores and breakdown."""
    m = _make_match(hours_offset=-5.0, actual_home=3, actual_away=1)
    m.kickoff_utc = datetime(2026, 6, 2, 15, 0, 0)
    bd = {"result": 3, "goals": 1, "exact": 0, "total": 4}
    p = _make_prediction(
        match=m, predicted_home=3, predicted_away=1, points_awarded=4, points_breakdown=bd
    )

    db = _mock_db(
        [
            _row(None),
            _count(0),
            _count(0),
            _row(None),
            _all([(p, m)]),
        ]
    )
    data = await _call_home(db)

    rm = data["rollup"]["matches"][0]
    assert rm["kickoff_utc"] == "2026-06-02T15:00:00Z"  # U27.B2
    assert rm["actual_home"] == 3
    assert rm["actual_away"] == 1
    assert rm["predicted_home"] == 3
    assert rm["predicted_away"] == 1
    assert rm["points_breakdown"] == bd


@pytest.mark.asyncio
async def test_home_rollup_uses_team_labels_when_team_ids_present() -> None:
    """Rollup match with team IDs → labels built from team names + flags."""
    team_id = uuid.uuid4()
    away_id = uuid.uuid4()
    m = _make_match(hours_offset=-5.0)
    m.kickoff_utc = datetime(2026, 6, 2, 15, 0, 0)
    m.home_team_id = team_id
    m.away_team_id = away_id

    home_team = MagicMock()
    home_team.id = team_id
    home_team.name = "Brazil"
    home_team.flag_emoji = "🇧🇷"

    away_team = MagicMock()
    away_team.id = away_id
    away_team.name = "France"
    away_team.flag_emoji = "🇫🇷"

    p = _make_prediction(match=m, points_awarded=5)

    db = _mock_db(
        [
            _row(None),
            _count(0),
            _count(0),
            _row(None),
            _all([(p, m)]),  # rollup rows
            _scalars([home_team, away_team]),  # rollup team lookup
        ]
    )
    data = await _call_home(db)

    rm = data["rollup"]["matches"][0]
    assert rm["home_label"] == "🇧🇷 Brazil"
    assert rm["away_label"] == "🇫🇷 France"
    assert rm["home_flag"] == "🇧🇷"
    assert rm["away_flag"] == "🇫🇷"
