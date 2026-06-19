"""Tests for Phase 10.3 — notification trigger wiring."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.league import League
from src.models.match import MatchStatus
from src.models.notification import NotificationType
from src.models.prediction import LeaderboardSnapshot
from src.models.profile import Profile
from src.services.notification_triggers import (
    MatchUpdate,
    check_deadline_warnings,
    check_evening_kickoff_warnings,
    check_pick_confirmations,
    notify_auto_sync_failed,
    notify_invite_accepted,
    notify_kickoff_changed,
    notify_leaderboard_shifts,
    notify_match_locked,
    notify_match_postponed,
    notify_result_detected,
    notify_round_complete,
    notify_special_results_awarded,
    notify_tournament_started,
    send_daily_prediction_digest,
)
from src.services.prediction_reminders import PickConfirmationTarget, UnpredictedDigestTarget

_NT = "src.services.notification_triggers"
_SEND = f"{_NT}.send_notification"
_TEAM = f"{_NT}._team_name"
_LB_SHIFTS = f"{_NT}.notify_leaderboard_shifts"
_RC = f"{_NT}.notify_round_complete"
_ACTIVE_PLAYERS = f"{_NT}._active_players"
_DIGEST_TARGETS = f"{_NT}.unpredicted_digest_targets_for_window"
_PICK_TARGETS = f"{_NT}.submitted_prediction_targets_for_window"
_UNPREDICTED = f"{_NT}.active_players_without_submitted_prediction_for_match"
_EVENING_PICK_TARGETS = f"{_NT}.submitted_prediction_targets_for_window"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _match_update(**kwargs: Any) -> MatchUpdate:
    defaults: dict[str, Any] = {
        "event_type": "test",
        "match_id": uuid.uuid4(),
        "stage": "group_stage",
        "home_team_id": None,
        "away_team_id": None,
        "home_placeholder": "France",
        "away_placeholder": "Germany",
    }
    defaults.update(kwargs)
    return MatchUpdate(**defaults)


def _player(role: str = "player") -> MagicMock:
    p = MagicMock(spec=Profile)
    p.avatar_url = None  # U23: prevent MagicMock default from failing Pydantic
    p.id = uuid.uuid4()
    p.display_name = "Alice"
    p.timezone = "UTC"
    p.is_active = True
    p.deleted_at = None
    p.role = role
    return p


def _snap(
    player_id: uuid.UUID,
    rank: int,
    match_id: uuid.UUID,
    league_id: uuid.UUID | None = None,
) -> MagicMock:
    s = MagicMock(spec=LeaderboardSnapshot)
    s.player_id = player_id
    s.rank = rank
    s.triggered_by_match_id = match_id
    s.league_id = league_id or uuid.uuid4()
    return s


def _league(
    name: str = "The Steele Spreadsheet",
    slug: str = "steele-spreadsheet",
    league_id: uuid.UUID | None = None,
) -> MagicMock:
    lg = MagicMock(spec=League)
    lg.id = league_id or uuid.uuid4()
    lg.name = name
    lg.slug = slug
    return lg


def _match(match_id: uuid.UUID | None = None) -> MagicMock:
    m = MagicMock()
    m.id = match_id or uuid.uuid4()
    m.stage = "group"
    m.status = MatchStatus.scheduled
    m.kickoff_utc = datetime(2026, 6, 14, 18, 0)
    m.home_team_id = None
    m.away_team_id = None
    m.home_team_placeholder = "England"
    m.away_team_placeholder = "France"
    m.deleted_at = None
    return m


# ── notify_match_locked ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_notify_match_locked_calls_send_for_all_players() -> None:
    update = _match_update()
    players = [_player(), _player()]
    session = AsyncMock()
    session.execute.return_value = MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=players)))
    )

    with (
        patch(_SEND, new_callable=AsyncMock) as mock_send,
        patch(_TEAM, new_callable=AsyncMock, return_value="France"),
    ):
        await notify_match_locked(session, update)

    assert mock_send.call_count == len(players)
    for call_args in mock_send.call_args_list:
        assert call_args.args[2] == NotificationType.match_locked


# ── notify_result_detected ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_notify_result_detected_dispatches_dependent_triggers() -> None:
    update = _match_update(event_type="finished", home_score=2, away_score=1)
    players = [_player()]
    session = AsyncMock()
    session.execute.return_value = MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=players)))
    )

    with (
        patch(_SEND, new_callable=AsyncMock) as mock_send,
        patch(_TEAM, new_callable=AsyncMock, return_value="France"),
        patch(_LB_SHIFTS, new_callable=AsyncMock) as mock_lb,
        patch(_RC, new_callable=AsyncMock) as mock_rc,
    ):
        mock_lb.return_value = set()
        await notify_result_detected(session, update)

    # result notification + leaderboard_shifts + round_complete both fired
    mock_lb.assert_awaited_once_with(session, update.match_id, tag=f"result-{update.match_id}")
    mock_rc.assert_awaited_once_with(session, update.stage)
    assert mock_send.call_count >= 1


@pytest.mark.asyncio
async def test_notify_result_detected_skips_broadcast_for_players_who_moved() -> None:
    """Players who got a leaderboard-move push are not also sent the generic result."""
    update = _match_update(event_type="finished", home_score=2, away_score=1)
    mover = _player()
    bystander = _player()
    session = AsyncMock()
    session.execute.return_value = MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[mover, bystander])))
    )

    with (
        patch(_SEND, new_callable=AsyncMock) as mock_send,
        patch(_TEAM, new_callable=AsyncMock, return_value="France"),
        patch(_LB_SHIFTS, new_callable=AsyncMock, return_value={mover.id}),
        patch(_RC, new_callable=AsyncMock),
    ):
        await notify_result_detected(session, update)

    assert mock_send.call_count == 1
    call = mock_send.call_args
    assert call.args[1] == bystander.id
    assert call.args[2] == NotificationType.result_detected
    assert call.kwargs["data"] == {"url": f"/matches/{update.match_id}"}
    assert call.kwargs["tag"] == f"result-{update.match_id}"


# ── notify_leaderboard_shifts ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_notify_leaderboard_shifts_names_league_and_deep_links() -> None:
    match_id = uuid.uuid4()
    player_id = uuid.uuid4()
    league_id = uuid.uuid4()
    league = _league(name="The Steele Spreadsheet", slug="steele-spreadsheet", league_id=league_id)
    new_snap = _snap(player_id, 2, match_id, league_id=league_id)
    old_snap = _snap(player_id, 5, uuid.uuid4(), league_id=league_id)

    session = AsyncMock()
    # execute order: new snapshots, league lookup, previous snapshot per league
    session.execute.side_effect = [
        MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[new_snap])))
        ),
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[league])))),
        MagicMock(scalar_one_or_none=MagicMock(return_value=old_snap)),
    ]

    with patch(_SEND, new_callable=AsyncMock) as mock_send:
        moved = await notify_leaderboard_shifts(session, match_id)

    mock_send.assert_awaited_once()
    call = mock_send.call_args
    assert call.args[2] == NotificationType.leaderboard_shift
    assert "#2" in call.args[3]
    assert "The Steele Spreadsheet" in call.args[3]  # league named in the title
    assert call.kwargs["data"] == {"url": "/leagues/steele-spreadsheet/leaderboard"}
    assert moved == {player_id}


@pytest.mark.asyncio
async def test_notify_leaderboard_shifts_consolidates_multiple_leagues() -> None:
    """A multi-league player gets ONE summary push, not one per league."""
    match_id = uuid.uuid4()
    player_id = uuid.uuid4()
    la, lb = uuid.uuid4(), uuid.uuid4()
    league_a = _league(name="Work League", slug="work", league_id=la)
    league_b = _league(name="Family", slug="family", league_id=lb)
    new_a = _snap(player_id, 2, match_id, league_id=la)  # up 4 -> 2
    new_b = _snap(player_id, 5, match_id, league_id=lb)  # down 3 -> 5
    old_a = _snap(player_id, 4, uuid.uuid4(), league_id=la)
    old_b = _snap(player_id, 3, uuid.uuid4(), league_id=lb)

    session = AsyncMock()
    session.execute.side_effect = [
        MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[new_a, new_b])))
        ),
        MagicMock(
            scalars=MagicMock(
                return_value=MagicMock(all=MagicMock(return_value=[league_a, league_b]))
            )
        ),
        MagicMock(scalar_one_or_none=MagicMock(return_value=old_a)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=old_b)),
    ]

    with patch(_SEND, new_callable=AsyncMock) as mock_send:
        moved = await notify_leaderboard_shifts(session, match_id)

    mock_send.assert_awaited_once()
    call = mock_send.call_args
    assert "2 leagues" in call.args[3]
    assert "Work League" in call.args[4] and "Family" in call.args[4]
    assert call.kwargs["data"] == {"url": "/leagues"}
    assert moved == {player_id}


@pytest.mark.asyncio
async def test_notify_leaderboard_shifts_no_send_when_rank_unchanged() -> None:
    match_id = uuid.uuid4()
    player_id = uuid.uuid4()
    league_id = uuid.uuid4()
    league = _league(league_id=league_id)
    new_snap = _snap(player_id, 3, match_id, league_id=league_id)
    old_snap = _snap(player_id, 3, uuid.uuid4(), league_id=league_id)

    session = AsyncMock()
    session.execute.side_effect = [
        MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[new_snap])))
        ),
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[league])))),
        MagicMock(scalar_one_or_none=MagicMock(return_value=old_snap)),
    ]

    with patch(_SEND, new_callable=AsyncMock) as mock_send:
        moved = await notify_leaderboard_shifts(session, match_id)

    mock_send.assert_not_awaited()
    assert moved == set()


# ── notify_round_complete ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_notify_round_complete_fires_when_all_done() -> None:
    players = [_player()]
    session = AsyncMock()
    # total = 3, completed = 3 → fire
    session.execute.side_effect = [
        MagicMock(scalar=MagicMock(return_value=3)),  # total
        MagicMock(scalar=MagicMock(return_value=3)),  # done
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=players)))),
    ]
    with patch(_SEND, new_callable=AsyncMock) as mock_send:
        await notify_round_complete(session, "group_stage")
    mock_send.assert_awaited()


@pytest.mark.asyncio
async def test_notify_round_complete_no_fire_when_incomplete() -> None:
    session = AsyncMock()
    session.execute.side_effect = [
        MagicMock(scalar=MagicMock(return_value=3)),  # total
        MagicMock(scalar=MagicMock(return_value=1)),  # done — not all finished
    ]
    with patch(_SEND, new_callable=AsyncMock) as mock_send:
        await notify_round_complete(session, "group_stage")
    mock_send.assert_not_awaited()


# ── notify_match_postponed ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_notify_match_postponed() -> None:
    update = _match_update(event_type="postponed")
    players = [_player()]
    session = AsyncMock()
    session.execute.return_value = MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=players)))
    )
    with (
        patch(_SEND, new_callable=AsyncMock) as mock_send,
        patch(_TEAM, new_callable=AsyncMock, return_value="X"),
    ):
        await notify_match_postponed(session, update)
    for call in mock_send.call_args_list:
        assert call.args[2] == NotificationType.match_postponed


# ── notify_kickoff_changed ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_notify_kickoff_changed_includes_new_time() -> None:
    update = _match_update(
        event_type="kickoff_changed",
        new_kickoff=datetime(2026, 6, 14, 18, 0),
    )
    players = [_player()]
    session = AsyncMock()
    session.execute.return_value = MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=players)))
    )
    with (
        patch(_SEND, new_callable=AsyncMock) as mock_send,
        patch(_TEAM, new_callable=AsyncMock, return_value="X"),
    ):
        await notify_kickoff_changed(session, update)
    assert mock_send.call_count == 1
    assert "18:00" in mock_send.call_args.args[4]


# ── notify_invite_accepted ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_notify_invite_accepted_notifies_admins_only() -> None:
    admin = _player(role="admin")
    session = AsyncMock()
    session.execute.return_value = MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[admin])))
    )
    with patch(_SEND, new_callable=AsyncMock) as mock_send:
        await notify_invite_accepted(session, "Craig")
    assert mock_send.call_count == 1
    assert "Craig" in mock_send.call_args.args[4]


# ── notify_special_results_awarded ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_notify_special_results_awarded() -> None:
    players = [_player(), _player()]
    session = AsyncMock()
    session.execute.return_value = MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=players)))
    )
    with patch(_SEND, new_callable=AsyncMock) as mock_send:
        await notify_special_results_awarded(session, "tournament_winner")
    assert mock_send.call_count == len(players)
    for call in mock_send.call_args_list:
        assert call.args[2] == NotificationType.special_results


# ── notify_auto_sync_failed ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_notify_auto_sync_failed_sends_to_admins() -> None:
    admin = _player(role="admin")
    session = AsyncMock()
    session.execute.return_value = MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[admin])))
    )
    with patch(_SEND, new_callable=AsyncMock) as mock_send:
        await notify_auto_sync_failed(session, "Connection refused")
    assert mock_send.call_count == 1
    assert mock_send.call_args.args[2] == NotificationType.auto_sync_failed


# ── check_deadline_warnings ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_deadline_warning_fires_for_imminent_match() -> None:

    from src.services.notification_triggers import _warned_match_ids

    match_id = uuid.uuid4()
    match = MagicMock()
    match.id = match_id
    match.stage = "group_stage"
    match.status = MatchStatus.scheduled
    match.kickoff_utc = datetime(2026, 6, 14, 18, 0)
    match.home_team_id = None
    match.away_team_id = None
    match.home_team_placeholder = "France"
    match.away_team_placeholder = "Germany"
    match.deleted_at = None

    _warned_match_ids.discard((match_id, 15))

    players = [_player()]
    session_mock = AsyncMock()
    session_mock.execute.side_effect = [
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[match])))),
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=players)))),
    ]

    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=session_mock)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    now = datetime(2026, 6, 14, 17, 44)  # 16 min before 18:00, within 14–16 min window
    with (
        patch(_SEND, new_callable=AsyncMock) as mock_send,
        patch(_TEAM, new_callable=AsyncMock, return_value="France"),
    ):
        count = await check_deadline_warnings(mock_factory, now=now)

    assert count == 1
    mock_send.assert_awaited()
    assert (match_id, 15) in _warned_match_ids


@pytest.mark.asyncio
async def test_deadline_warning_not_double_sent() -> None:
    from src.services.notification_triggers import _warned_match_ids

    match_id = uuid.uuid4()
    _warned_match_ids.add((match_id, 15))  # already warned

    match = MagicMock()
    match.id = match_id
    match.status = MatchStatus.scheduled
    match.kickoff_utc = datetime(2026, 6, 14, 18, 0)
    match.deleted_at = None

    session_mock = AsyncMock()
    session_mock.execute.return_value = MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[match])))
    )

    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=session_mock)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    now = datetime(2026, 6, 14, 17, 44)
    with patch(_SEND, new_callable=AsyncMock) as mock_send:
        count = await check_deadline_warnings(mock_factory, now=now)

    assert count == 0
    mock_send.assert_not_awaited()


# ── prediction reminders ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_daily_prediction_digest_sends_one_deep_linked_digest_per_target() -> None:
    target_player = _player()
    fully_predicted = _player()
    target_match = _match()
    session_mock = AsyncMock()

    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=session_mock)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    with (
        patch(
            _ACTIVE_PLAYERS,
            new_callable=AsyncMock,
            return_value=[target_player, fully_predicted],
        ),
        patch(
            _DIGEST_TARGETS,
            new_callable=AsyncMock,
            return_value=[
                UnpredictedDigestTarget(player=target_player, matches=[target_match, _match()])
            ],
        ),
        patch(_SEND, new_callable=AsyncMock) as mock_send,
    ):
        count = await send_daily_prediction_digest(
            mock_factory,
            now=datetime(2026, 6, 14, 9, 0),
        )

    assert count == 1
    mock_send.assert_awaited_once()
    call = mock_send.call_args
    assert call.args[2] == NotificationType.predict_reminder
    assert "2 matches" in call.args[4]
    assert call.kwargs["data"] == {"url": "/predictions"}
    session_mock.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_daily_prediction_digest_no_targets_no_commit() -> None:
    player = _player()
    session_mock = AsyncMock()

    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=session_mock)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    with (
        patch(_ACTIVE_PLAYERS, new_callable=AsyncMock, return_value=[player]),
        patch(_DIGEST_TARGETS, new_callable=AsyncMock, return_value=[]),
        patch(_SEND, new_callable=AsyncMock) as mock_send,
    ):
        count = await send_daily_prediction_digest(
            mock_factory,
            now=datetime(2026, 6, 14, 9, 0),
        )

    assert count == 0
    mock_send.assert_not_awaited()
    session_mock.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_pick_confirmation_sends_only_for_submitted_prediction_targets() -> None:
    player = _player()
    match = _match()
    prediction = MagicMock()
    prediction.predicted_home = 2
    prediction.predicted_away = 1
    target = PickConfirmationTarget(player=player, match=match, prediction=prediction)
    session_mock = AsyncMock()
    session_mock.scalar = AsyncMock(return_value=0)  # not yet sent
    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=session_mock)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    with (
        patch(_PICK_TARGETS, new_callable=AsyncMock, return_value=[target]),
        patch(_TEAM, new_callable=AsyncMock, side_effect=["England", "France"]),
        patch(_SEND, new_callable=AsyncMock) as mock_send,
    ):
        count = await check_pick_confirmations(mock_factory, now=datetime(2026, 6, 14, 17, 44))

    assert count == 1
    mock_send.assert_awaited_once()
    call = mock_send.call_args
    assert call.args[2] == NotificationType.pick_confirmation
    assert "England v France" in call.args[3]
    assert "2–1" in call.args[4]
    assert call.kwargs["data"] == {"url": "/predictions"}
    assert call.kwargs["match_id"] == match.id
    session_mock.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_deadline_warning_15_only_sends_to_unpredicted_players() -> None:
    from src.services.notification_triggers import _warned_match_ids

    match_id = uuid.uuid4()
    _warned_match_ids.discard((match_id, 15))
    match = _match(match_id)

    unpredicted_player = _player()
    session_mock = AsyncMock()
    session_mock.execute.return_value = MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[match])))
    )

    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=session_mock)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    now = datetime(2026, 6, 14, 17, 44)
    with (
        patch(_SEND, new_callable=AsyncMock) as mock_send,
        patch(_TEAM, new_callable=AsyncMock, return_value="France"),
        patch(_UNPREDICTED, new_callable=AsyncMock, return_value=[unpredicted_player]),
    ):
        count = await check_deadline_warnings(mock_factory, now=now, unpredicted_only=True)

    assert count == 1
    mock_send.assert_awaited_once()
    call = mock_send.call_args
    assert call.args[1] == unpredicted_player.id
    assert call.args[2] == NotificationType.deadline_warning


@pytest.mark.asyncio
async def test_pick_confirmation_not_double_sent() -> None:
    player = _player()
    match = _match()
    prediction = MagicMock()
    prediction.predicted_home = 1
    prediction.predicted_away = 1
    session_mock = AsyncMock()
    session_mock.scalar = AsyncMock(return_value=1)  # already sent

    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=session_mock)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    with (
        patch(
            _PICK_TARGETS,
            new_callable=AsyncMock,
            return_value=[
                PickConfirmationTarget(player=player, match=match, prediction=prediction)
            ],
        ),
        patch(_SEND, new_callable=AsyncMock) as mock_send,
    ):
        count = await check_pick_confirmations(mock_factory, now=datetime(2026, 6, 14, 17, 44))

    assert count == 0
    mock_send.assert_not_awaited()
    session_mock.commit.assert_not_called()


# ── check_evening_kickoff_warnings ───────────────────────────────────────────


def _make_factory(session_mock: AsyncMock) -> MagicMock:
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session_mock)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return factory


@pytest.mark.asyncio
async def test_evening_warning_no_op_outside_21_uk() -> None:
    # 19:59 UTC = 20:59 BST — should not fire
    now = datetime(2026, 6, 14, 18, 59)
    session_mock = AsyncMock()
    with patch(_SEND, new_callable=AsyncMock) as mock_send:
        count = await check_evening_kickoff_warnings(_make_factory(session_mock), now=now)
    assert count == 0
    mock_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_evening_warning_sends_to_unpredicted_at_21_uk() -> None:
    from src.services.notification_triggers import _evening_warned

    match = _match()
    match.kickoff_utc = datetime(2026, 6, 14, 23, 0)
    player = _player()

    session_mock = AsyncMock()
    session_mock.scalar = AsyncMock(return_value=0)
    session_mock.execute.return_value = MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[match])))
    )

    _evening_warned.discard((match.id, player.id))

    now = datetime(2026, 6, 14, 20, 0)  # 20:00 UTC = 21:00 BST
    with (
        patch(_EVENING_PICK_TARGETS, new_callable=AsyncMock, return_value=[]),
        patch(_UNPREDICTED, new_callable=AsyncMock, return_value=[player]),
        patch(_TEAM, new_callable=AsyncMock, return_value="England"),
        patch(_SEND, new_callable=AsyncMock) as mock_send,
    ):
        count = await check_evening_kickoff_warnings(_make_factory(session_mock), now=now)

    assert count == 1
    mock_send.assert_awaited_once()
    call = mock_send.call_args
    assert call.args[1] == player.id
    assert call.args[2] == NotificationType.predict_reminder
    assert "Predict before kickoff" in call.args[4]


@pytest.mark.asyncio
async def test_evening_warning_sends_score_to_predicted() -> None:
    from src.services.notification_triggers import _evening_warned

    match = _match()
    match.kickoff_utc = datetime(2026, 6, 14, 23, 0)
    player = _player()
    prediction = MagicMock()
    prediction.predicted_home = 2
    prediction.predicted_away = 0
    target = PickConfirmationTarget(player=player, match=match, prediction=prediction)

    session_mock = AsyncMock()
    session_mock.scalar = AsyncMock(return_value=0)
    session_mock.execute.return_value = MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    )

    _evening_warned.discard((match.id, player.id))

    now = datetime(2026, 6, 14, 20, 0)
    with (
        patch(_EVENING_PICK_TARGETS, new_callable=AsyncMock, return_value=[target]),
        patch(_UNPREDICTED, new_callable=AsyncMock, return_value=[]),
        patch(_TEAM, new_callable=AsyncMock, return_value="England"),
        patch(_SEND, new_callable=AsyncMock) as mock_send,
    ):
        count = await check_evening_kickoff_warnings(_make_factory(session_mock), now=now)

    assert count == 1
    mock_send.assert_awaited_once()
    call = mock_send.call_args
    assert "2–0" in call.args[4]
    assert "still edit" in call.args[4]


@pytest.mark.asyncio
async def test_evening_warning_dedup_via_db() -> None:
    from src.services.notification_triggers import _evening_warned

    match = _match()
    match.kickoff_utc = datetime(2026, 6, 14, 23, 0)
    player = _player()

    session_mock = AsyncMock()
    session_mock.scalar = AsyncMock(return_value=1)  # already sent today
    session_mock.execute.return_value = MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[match])))
    )

    _evening_warned.discard((match.id, player.id))

    now = datetime(2026, 6, 14, 20, 0)
    with (
        patch(_EVENING_PICK_TARGETS, new_callable=AsyncMock, return_value=[]),
        patch(_UNPREDICTED, new_callable=AsyncMock, return_value=[player]),
        patch(_TEAM, new_callable=AsyncMock, return_value="England"),
        patch(_SEND, new_callable=AsyncMock) as mock_send,
    ):
        count = await check_evening_kickoff_warnings(_make_factory(session_mock), now=now)

    assert count == 0
    mock_send.assert_not_awaited()


# ── notify_match_locked (updated copy + deep link) ───────────────────────────


@pytest.mark.asyncio
async def test_notify_match_locked_includes_deep_link() -> None:
    """notify_match_locked passes data.url = /matches/<id> to every push."""
    match_id = uuid.uuid4()
    update = _match_update(match_id=match_id)
    players = [_player()]
    session = AsyncMock()
    session.execute.return_value = MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=players)))
    )

    with (
        patch(_SEND, new_callable=AsyncMock) as mock_send,
        patch(_TEAM, new_callable=AsyncMock, return_value="France"),
    ):
        await notify_match_locked(session, update)

    assert mock_send.call_count == 1
    kwargs = mock_send.call_args.kwargs
    assert kwargs.get("data") == {"url": f"/matches/{match_id}"}


@pytest.mark.asyncio
async def test_notify_match_locked_title_mentions_kickoff() -> None:
    """Title contains the kicked-off indication and body mentions everyone picked."""
    update = _match_update()
    players = [_player()]
    session = AsyncMock()
    session.execute.return_value = MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=players)))
    )

    with (
        patch(_SEND, new_callable=AsyncMock) as mock_send,
        patch(_TEAM, new_callable=AsyncMock, return_value="France"),
    ):
        await notify_match_locked(session, update)

    call = mock_send.call_args
    title: str = call.args[3]
    body: str = call.args[4]
    assert "kicked off" in title.lower()
    assert "picked" in body.lower() or "predicted" in body.lower()


# ── notify_tournament_started ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_notify_tournament_started_sends_to_all_active_players() -> None:
    """notify_tournament_started broadcasts specials_revealed to every active player."""
    players = [_player(), _player(), _player()]
    session = AsyncMock()
    session.execute.return_value = MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=players)))
    )

    with patch(_SEND, new_callable=AsyncMock) as mock_send:
        await notify_tournament_started(session)

    assert mock_send.call_count == len(players)
    for call_args in mock_send.call_args_list:
        assert call_args.args[2] == NotificationType.specials_revealed


@pytest.mark.asyncio
async def test_notify_tournament_started_deep_links_to_specials() -> None:
    """The specials_revealed notification carries data.url pointing at the specials page."""
    players = [_player()]
    session = AsyncMock()
    session.execute.return_value = MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=players)))
    )

    with patch(_SEND, new_callable=AsyncMock) as mock_send:
        await notify_tournament_started(session)

    kwargs = mock_send.call_args.kwargs
    assert kwargs.get("data") == {"url": "/predictions/specials"}
