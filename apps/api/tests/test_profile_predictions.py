"""U24 — reveal-gated player-profile predictions.

These tests pin the **privacy invariant**: the
``GET /api/v1/players/{id}/profile-predictions`` endpoint must NEVER return a
prediction before it locks (group + knockout per-match kickoff, specials at the
opening kickoff), and MUST return it to a league-mate the instant it locks.

The endpoint funnels every section through the single shared reveal gate
(:mod:`src.reveal_gate`); :func:`test_shared_gate_predicate` asserts that one
gate directly so the rule can't silently diverge per call-site.
"""

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
from src.models.prediction import (
    KnockoutPrediction,
    Prediction,
    SpecialPrediction,
    SpecialPredictionType,
)
from src.models.profile import PlayerRole, Profile
from src.models.team import Team, TournamentStage
from src.reveal_gate import match_prediction_revealed, specials_revealed

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


HOME_TEAM_ID = uuid.uuid4()
AWAY_TEAM_ID = uuid.uuid4()


def _make_player(player_id: uuid.UUID | None = None) -> Profile:
    p = MagicMock(spec=Profile)
    p.avatar_url = None  # U23: prevent MagicMock default from failing Pydantic
    p.id = player_id or uuid.uuid4()
    p.display_name = "TestPlayer"
    p.role = PlayerRole.player
    p.timezone = "UTC"
    p.deleted_at = None
    p.created_at = _now()
    return p


def _make_team(team_id: uuid.UUID, name: str, flag: str = "🏳️") -> Team:
    t = MagicMock(spec=Team)
    t.id = team_id
    t.name = name
    t.code = name[:3].upper()
    t.flag_emoji = flag
    return t


def _make_match(
    *,
    stage: TournamentStage = TournamentStage.group,
    status: MatchStatus = MatchStatus.scheduled,
    kickoff_utc: datetime | None = None,
    home_team_id: uuid.UUID | None = HOME_TEAM_ID,
    away_team_id: uuid.UUID | None = AWAY_TEAM_ID,
) -> Match:
    m = MagicMock(spec=Match)
    m.id = uuid.uuid4()
    m.match_number = 1
    m.stage = stage
    m.group_id = uuid.uuid4() if stage == TournamentStage.group else None
    m.home_team_id = home_team_id
    m.away_team_id = away_team_id
    m.home_team_placeholder = "Home"
    m.away_team_placeholder = "Away"
    m.kickoff_utc = kickoff_utc if kickoff_utc is not None else _now() + timedelta(hours=1)
    m.status = status
    m.actual_home_score = None
    m.actual_away_score = None
    m.deleted_at = None
    return m


def _make_group_pred(player_id: uuid.UUID, match_id: uuid.UUID) -> Prediction:
    p = MagicMock(spec=Prediction)
    p.id = uuid.uuid4()
    p.player_id = player_id
    p.match_id = match_id
    p.predicted_home = 2
    p.predicted_away = 1
    p.points_awarded = None
    p.points_breakdown = None
    p.deleted_at = None
    return p


def _make_ko_pred(player_id: uuid.UUID, match_id: uuid.UUID) -> KnockoutPrediction:
    p = MagicMock(spec=KnockoutPrediction)
    p.id = uuid.uuid4()
    p.player_id = player_id
    p.match_id = match_id
    p.predicted_winner_id = HOME_TEAM_ID
    p.points_awarded = None
    return p


def _make_special(player_id: uuid.UUID) -> SpecialPrediction:
    p = MagicMock(spec=SpecialPrediction)
    p.id = uuid.uuid4()
    p.player_id = player_id
    p.prediction_type = SpecialPredictionType.tournament_winner
    p.predicted_team_id = HOME_TEAM_ID
    p.predicted_player_id = None
    p.predicted_player_name = None
    p.points_awarded = None
    return p


def _scalar_one(value: object) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _scalars(items: list) -> MagicMock:
    r = MagicMock()
    r.scalars.return_value.all.return_value = items
    return r


def _rows(pairs: list[tuple]) -> MagicMock:
    r = MagicMock()
    r.all.return_value = pairs
    return r


def _stub_db(execute_results: list) -> AsyncMock:
    mock_db = AsyncMock(spec=AsyncSession)
    mock_db.execute = AsyncMock(side_effect=execute_results)
    return mock_db


@asynccontextmanager
async def _override(mock_db: AsyncMock, player: Profile) -> AsyncGenerator[None, None]:
    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_current_player] = lambda: player
    try:
        yield
    finally:
        app.dependency_overrides.clear()


async def _call(
    target: Profile,
    requester: Profile,
    execute_results: list,
    *,
    shared: frozenset[uuid.UUID] | None = None,
) -> tuple[int, dict]:
    """Drive the endpoint with a fixed db.execute() result sequence.

    Execute order inside get_profile_predictions (shared_league_player_ids is
    patched, so it makes no db call):
      0: target profile lookup       (scalar_one_or_none)
      1: group rows                  (.all)
      2: knockout rows               (.all)
      3: opening match               (scalar_one_or_none)
      4: specials rows               (.scalars().all)   [only if tournament started]
      5: teams batch                 (.scalars().all)   [only if any team referenced]
    Callers pass exactly the results their scenario reaches.
    """
    db = _stub_db(execute_results)
    if shared is None:
        shared = frozenset({requester.id, target.id})
    with patch(
        "src.routers.players.shared_league_player_ids",
        return_value=shared,
    ):
        async with _override(db, requester):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    f"/api/v1/players/{target.id}/profile-predictions",
                    headers={"Authorization": "Bearer x"},
                )
    return resp.status_code, (resp.json() if resp.status_code == 200 else {})


# ---------------------------------------------------------------------------
# The shared gate itself
# ---------------------------------------------------------------------------


def test_shared_gate_predicate() -> None:
    """One gate, used by group + knockout + (via opening match) specials."""
    now = _now()
    future = _make_match(kickoff_utc=now + timedelta(hours=1))
    past = _make_match(kickoff_utc=now - timedelta(seconds=1))
    assert match_prediction_revealed(future, now) is False
    assert match_prediction_revealed(past, now) is True

    # An admin void (cancelled/postponed) reveals even with a future kickoff —
    # the fixture won't be played, so the prediction is frozen.
    voided = _make_match(kickoff_utc=now + timedelta(hours=1), status=MatchStatus.cancelled)
    assert match_prediction_revealed(voided, now) is True

    # Specials: hidden until the opening match kicks off; hidden with none seeded.
    assert specials_revealed(None, now) is False
    assert specials_revealed(future, now) is False
    assert specials_revealed(past, now) is True


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_profile_predictions_not_found() -> None:
    requester = _make_player()
    target = _make_player()
    status_code, _ = await _call(target, requester, [_scalar_one(None)])
    assert status_code == 404


@pytest.mark.asyncio
async def test_profile_predictions_non_league_mate_forbidden() -> None:
    requester = _make_player()
    target = _make_player()
    # Target exists but requester shares no league → 403, before any data read.
    status_code, _ = await _call(
        target,
        requester,
        [_scalar_one(target)],
        shared=frozenset({requester.id}),
    )
    assert status_code == 403


# ---------------------------------------------------------------------------
# PRIVACY INVARIANT — pre-lock predictions never leak (group + knockout + specials)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pre_lock_predictions_never_returned() -> None:
    """The linchpin: every section's pre-lock prediction is dropped.

    Group + knockout matches kick off in the future and the tournament has not
    started, so all three lists must come back empty even though the rows exist.
    """
    requester = _make_player()
    target = _make_player()

    future_group = _make_match(stage=TournamentStage.group, kickoff_utc=_now() + timedelta(hours=2))
    future_ko = _make_match(stage=TournamentStage.r32, kickoff_utc=_now() + timedelta(hours=2))
    future_opening = _make_match(
        stage=TournamentStage.group, kickoff_utc=_now() + timedelta(hours=2)
    )

    group_pred = _make_group_pred(target.id, future_group.id)
    ko_pred = _make_ko_pred(target.id, future_ko.id)

    # Execute order: profile, group rows, ko rows, opening match.
    # Specials are NOT fetched (tournament not started). Teams are NOT fetched
    # (no revealed rows → empty team set).
    status_code, body = await _call(
        target,
        requester,
        [
            _scalar_one(target),
            _rows([(group_pred, future_group)]),
            _rows([(ko_pred, future_ko)]),
            _scalar_one(future_opening),
        ],
    )

    assert status_code == 200, body
    assert body["group"] == [], "pre-lock GROUP prediction leaked"
    assert body["knockout"] == [], "pre-lock KNOCKOUT prediction leaked"
    assert body["specials"] == [], "pre-lock SPECIAL prediction leaked"
    assert body["specials_revealed"] is False


@pytest.mark.asyncio
async def test_specials_hidden_before_tournament_even_with_rows() -> None:
    """Specials stay empty pre-tournament and the row query is never issued."""
    requester = _make_player()
    target = _make_player()
    future_opening = _make_match(kickoff_utc=_now() + timedelta(hours=1))

    # No group/ko rows; opening match in the future. If the endpoint tried to
    # read specials it would hit a 5th execute and raise StopIteration → 500.
    status_code, body = await _call(
        target,
        requester,
        [
            _scalar_one(target),
            _rows([]),
            _rows([]),
            _scalar_one(future_opening),
        ],
    )
    assert status_code == 200, body
    assert body["specials"] == []
    assert body["specials_revealed"] is False


# ---------------------------------------------------------------------------
# PRIVACY INVARIANT — post-lock predictions ARE visible to league-mates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_lock_predictions_visible_to_league_mate() -> None:
    """The mirror of the leak test: once locked, every section is returned."""
    requester = _make_player()
    target = _make_player()

    past_group = _make_match(stage=TournamentStage.group, kickoff_utc=_now() - timedelta(minutes=5))
    past_ko = _make_match(stage=TournamentStage.r32, kickoff_utc=_now() - timedelta(minutes=5))
    past_opening = _make_match(stage=TournamentStage.group, kickoff_utc=_now() - timedelta(hours=3))

    group_pred = _make_group_pred(target.id, past_group.id)
    ko_pred = _make_ko_pred(target.id, past_ko.id)
    special = _make_special(target.id)

    home = _make_team(HOME_TEAM_ID, "Brazil", "🇧🇷")
    away = _make_team(AWAY_TEAM_ID, "Germany", "🇩🇪")

    # Execute order: profile, group rows, ko rows, opening match, specials rows,
    # teams batch (all revealed → team set non-empty).
    status_code, body = await _call(
        target,
        requester,
        [
            _scalar_one(target),
            _rows([(group_pred, past_group)]),
            _rows([(ko_pred, past_ko)]),
            _scalar_one(past_opening),
            _scalars([special]),
            _scalars([home, away]),
        ],
    )

    assert status_code == 200, body
    assert body["specials_revealed"] is True

    assert len(body["group"]) == 1
    assert body["group"][0]["predicted_home"] == 2
    assert body["group"][0]["predicted_away"] == 1
    assert body["group"][0]["home_team_name"] == "Brazil"

    assert len(body["knockout"]) == 1
    assert body["knockout"][0]["predicted_winner_id"] == str(HOME_TEAM_ID)
    assert body["knockout"][0]["predicted_winner_name"] == "Brazil"

    assert len(body["specials"]) == 1
    assert body["specials"][0]["prediction_type"] == "tournament_winner"
    assert body["specials"][0]["predicted_team_name"] == "Brazil"


@pytest.mark.asyncio
async def test_mixed_lock_states_only_locked_sections_returned() -> None:
    """A locked group match reveals; a still-scheduled knockout tie does not."""
    requester = _make_player()
    target = _make_player()

    past_group = _make_match(stage=TournamentStage.group, kickoff_utc=_now() - timedelta(minutes=5))
    future_ko = _make_match(stage=TournamentStage.r32, kickoff_utc=_now() + timedelta(hours=2))
    future_opening = _make_match(
        stage=TournamentStage.group, kickoff_utc=_now() + timedelta(hours=2)
    )

    group_pred = _make_group_pred(target.id, past_group.id)
    ko_pred = _make_ko_pred(target.id, future_ko.id)
    home = _make_team(HOME_TEAM_ID, "Brazil", "🇧🇷")
    away = _make_team(AWAY_TEAM_ID, "Germany", "🇩🇪")

    # Group locked (revealed) → team set non-empty → teams fetched.
    # Knockout still scheduled (hidden). Specials hidden (opening in future) so
    # specials rows are NOT fetched. Execute order: profile, group, ko, opening,
    # teams.
    status_code, body = await _call(
        target,
        requester,
        [
            _scalar_one(target),
            _rows([(group_pred, past_group)]),
            _rows([(ko_pred, future_ko)]),
            _scalar_one(future_opening),
            _scalars([home, away]),
        ],
    )

    assert status_code == 200, body
    assert len(body["group"]) == 1, "locked group prediction should be visible"
    assert body["knockout"] == [], "pre-lock knockout prediction leaked"
    assert body["specials"] == []
    assert body["specials_revealed"] is False
