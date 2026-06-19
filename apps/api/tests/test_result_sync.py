"""Unit tests for the auto result-fetch job (Phase 5.3).

These tests run without a database; the session is a MagicMock that
records the in-memory mutations the sync routine applies. Postgres-only
behaviour (the row-level lock, the scoring trigger) is exercised in the
integration job that runs against a real database in CI.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.match import Match, MatchStatus, ResultSource
from src.models.notification import (
    ActionType,
    ActorType,
    AuditLog,
    NotificationLog,
)
from src.models.team import TournamentStage
from src.services import result_sync
from src.services.football_data import (
    FDMatch,
    FDMatchesResponse,
    FDMatchStatus,
    FDScore,
    FDScoreLine,
    FDTeam,
    FootballDataServerError,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime(2026, 6, 11, 18, 30, 0)


def _make_match(
    *,
    fd_id: int = 419665,
    status: MatchStatus = MatchStatus.locked,
    stage: TournamentStage = TournamentStage.group,
    kickoff: datetime | None = None,
    result_source: ResultSource | None = None,
    original_kickoff: datetime | None = None,
    home_team_id: uuid.UUID | None = None,
    away_team_id: uuid.UUID | None = None,
) -> MagicMock:
    m = MagicMock(spec=Match)
    m.id = uuid.uuid4()
    m.stage = stage
    m.football_data_match_id = fd_id
    m.status = status
    m.match_number = 1
    m.kickoff_utc = kickoff or _now() - timedelta(minutes=30)
    m.original_kickoff_utc = original_kickoff
    m.locked_at = None
    m.home_team_id = home_team_id
    m.away_team_id = away_team_id
    m.home_team_placeholder = None
    m.away_team_placeholder = None
    m.actual_home_score = None
    m.actual_away_score = None
    m.extra_time = False
    m.penalties = False
    m.result_source = result_source
    m.result_entered_by = None
    m.last_synced_at = None
    m.deleted_at = None
    return m


def _fd_match(
    *,
    fd_id: int = 419665,
    status: FDMatchStatus = FDMatchStatus.FINISHED,
    stage: str = "GROUP_STAGE",
    utc_date: datetime | None = None,
    home_score: int | None = 2,
    away_score: int | None = 1,
    duration: str = "REGULAR",
    home_team_id: int | None = 1,
    away_team_id: int | None = 2,
    home_tla: str | None = "HOM",
    away_tla: str | None = "AWY",
    home_name: str | None = "Home",
    away_name: str | None = "Away",
) -> FDMatch:
    return FDMatch(
        id=fd_id,
        utcDate=utc_date or datetime(2026, 6, 11, 18, 0, 0, tzinfo=UTC),
        status=status,
        stage=stage,
        group="GROUP_A",
        homeTeam=FDTeam(id=home_team_id, name=home_name, tla=home_tla),
        awayTeam=FDTeam(id=away_team_id, name=away_name, tla=away_tla),
        score=FDScore(
            winner=None,
            duration=duration,
            fullTime=FDScoreLine(home=home_score, away=away_score),
        ),
    )


def _make_team(*, code: str, fd_team_id: int | None = None) -> MagicMock:
    team = MagicMock()
    team.id = uuid.uuid4()
    team.code = code
    team.football_data_team_id = fd_team_id
    return team


def _scalars(items: list[Any]) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = items[0] if items else None
    r.scalars.return_value.all.return_value = items
    return r


def _mock_session_factory(execute_results: list[MagicMock]) -> tuple[MagicMock, AsyncMock]:
    """Build a session_factory whose session.execute replays the given results."""
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=execute_results)
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()

    class _Ctx:
        async def __aenter__(self) -> AsyncMock:
            return session

        async def __aexit__(self, *a: object) -> None:
            return None

    factory = MagicMock(return_value=_Ctx())
    return factory, session


def _mock_client_factory(
    fd_matches: list[FDMatch] | None = None,
    raise_error: Exception | None = None,
) -> MagicMock:
    client = AsyncMock()
    if raise_error is not None:
        client.get_competition_matches = AsyncMock(side_effect=raise_error)
    else:
        client.get_competition_matches = AsyncMock(
            return_value=FDMatchesResponse(count=len(fd_matches or []), matches=fd_matches or [])
        )
    client.close = AsyncMock()
    return MagicMock(return_value=client)


@pytest.fixture(autouse=True)
def _reset_counter() -> None:
    result_sync.reset_failure_counter()


@pytest.fixture(autouse=True)
def _no_notify(monkeypatch: pytest.MonkeyPatch) -> None:
    with (
        patch("src.services.result_sync.notify_result_detected", new_callable=AsyncMock),
        patch("src.services.result_sync.notify_kickoff_changed", new_callable=AsyncMock),
        patch("src.services.result_sync.notify_match_postponed", new_callable=AsyncMock),
    ):
        yield


@pytest.fixture(autouse=True)
def _no_bracket_sync() -> Iterator[AsyncMock]:
    """Stub the knockout bracket resolver for every sync test.

    ``sync_results`` now calls ``sync_knockout_bracket`` after a finished
    result settles. The resolver issues several ``session.execute`` queries,
    which would exhaust this module's fixed mock ``execute`` side-effect queue,
    so it is patched to a no-op by default. Tests that assert on the call
    request this fixture and inspect the returned mock.
    """
    with patch("src.services.result_sync.sync_knockout_bracket", new_callable=AsyncMock) as mock:
        mock.return_value = 0
        yield mock


# ---------------------------------------------------------------------------
# FINISHED — new result
# ---------------------------------------------------------------------------


async def test_finished_match_writes_score_and_audit() -> None:
    match = _make_match(status=MatchStatus.locked)
    fd = _fd_match(status=FDMatchStatus.FINISHED, home_score=3, away_score=1)
    factory, session = _mock_session_factory([_scalars([match])])
    client_factory = _mock_client_factory([fd])

    count = await result_sync.sync_results(session_factory=factory, client_factory=client_factory)

    assert count == 1
    assert match.actual_home_score == 3
    assert match.actual_away_score == 1
    assert match.result_source == ResultSource.auto
    assert match.status == MatchStatus.completed
    assert match.result_entered_by is None
    audit = next(c.args[0] for c in session.add.call_args_list if isinstance(c.args[0], AuditLog))
    assert audit.actor_type == ActorType.system
    assert audit.action_type == ActionType.result_auto_fetched
    assert audit.target_id == match.id


# ---------------------------------------------------------------------------
# Idempotency — no-op when result_source is already set
# ---------------------------------------------------------------------------


async def test_finished_match_with_existing_result_is_noop() -> None:
    match = _make_match(status=MatchStatus.completed, result_source=ResultSource.manual)
    match.actual_home_score = 1
    match.actual_away_score = 0
    fd = _fd_match(status=FDMatchStatus.FINISHED, home_score=3, away_score=1)
    factory, session = _mock_session_factory([_scalars([match])])
    client_factory = _mock_client_factory([fd])

    count = await result_sync.sync_results(session_factory=factory, client_factory=client_factory)

    assert count == 0
    assert match.actual_home_score == 1
    assert match.actual_away_score == 0
    assert match.result_source == ResultSource.manual
    # No match-level audit row (sync_triggered system row is expected even for noops).
    assert not [
        c
        for c in session.add.call_args_list
        if isinstance(c.args[0], AuditLog) and c.args[0].action_type != ActionType.sync_triggered
    ]


# ---------------------------------------------------------------------------
# Race condition — admin manual entry between rows
# ---------------------------------------------------------------------------


async def test_race_with_manual_entry_skipped() -> None:
    """If a manual entry won the row-lock race, we observe result_source != None."""
    match = _make_match(status=MatchStatus.completed, result_source=ResultSource.override)
    match.actual_home_score = 2
    match.actual_away_score = 2
    fd = _fd_match(status=FDMatchStatus.FINISHED, home_score=4, away_score=0)
    factory, session = _mock_session_factory([_scalars([match])])
    client_factory = _mock_client_factory([fd])

    count = await result_sync.sync_results(session_factory=factory, client_factory=client_factory)

    assert count == 0
    # Admin's override stands.
    assert match.result_source == ResultSource.override
    assert match.actual_home_score == 2


# ---------------------------------------------------------------------------
# POSTPONED + CANCELLED + IN_PLAY status deltas
# ---------------------------------------------------------------------------


async def test_postponed_transitions_status_and_audits() -> None:
    match = _make_match(status=MatchStatus.scheduled)
    fd = _fd_match(status=FDMatchStatus.POSTPONED, home_score=None, away_score=None)
    factory, session = _mock_session_factory([_scalars([match])])
    client_factory = _mock_client_factory([fd])

    count = await result_sync.sync_results(session_factory=factory, client_factory=client_factory)

    assert count == 1
    assert match.status == MatchStatus.postponed
    audit = next(c.args[0] for c in session.add.call_args_list if isinstance(c.args[0], AuditLog))
    assert audit.action_type == ActionType.match_postponed
    assert audit.actor_type == ActorType.system


async def test_cancelled_transitions_status() -> None:
    match = _make_match(status=MatchStatus.scheduled)
    fd = _fd_match(status=FDMatchStatus.CANCELLED, home_score=None, away_score=None)
    factory, _ = _mock_session_factory([_scalars([match])])
    client_factory = _mock_client_factory([fd])

    await result_sync.sync_results(session_factory=factory, client_factory=client_factory)

    assert match.status == MatchStatus.cancelled


async def test_in_play_transitions_locked_to_live() -> None:
    match = _make_match(status=MatchStatus.locked)
    fd = _fd_match(status=FDMatchStatus.IN_PLAY, home_score=None, away_score=None)
    factory, _ = _mock_session_factory([_scalars([match])])
    client_factory = _mock_client_factory([fd])

    count = await result_sync.sync_results(session_factory=factory, client_factory=client_factory)

    assert count == 1
    assert match.status == MatchStatus.live


# ---------------------------------------------------------------------------
# Kickoff change — drift detection + lock-job re-registration
# ---------------------------------------------------------------------------


async def test_kickoff_change_updates_kickoff_and_preserves_original() -> None:
    original = datetime(2026, 6, 15, 18, 0, 0)
    new_kickoff = datetime(2026, 6, 15, 20, 0, 0)
    match = _make_match(status=MatchStatus.scheduled, kickoff=original)
    fd = _fd_match(
        status=FDMatchStatus.TIMED,
        utc_date=new_kickoff.replace(tzinfo=UTC),
        home_score=None,
        away_score=None,
    )
    factory, session = _mock_session_factory([_scalars([match])])
    client_factory = _mock_client_factory([fd])

    count = await result_sync.sync_results(session_factory=factory, client_factory=client_factory)

    assert count == 1
    # The periodic lock_due_matches job is the lock-job mechanism — it
    # picks up the new kickoff_utc on its next tick. That is the
    # "re-registration" path: we update the DB row only.
    assert match.kickoff_utc == new_kickoff
    assert match.original_kickoff_utc == original
    audit = next(c.args[0] for c in session.add.call_args_list if isinstance(c.args[0], AuditLog))
    assert audit.action_type == ActionType.kickoff_changed
    assert audit.changes is not None
    assert audit.changes["new_kickoff_utc"] == new_kickoff.isoformat()
    assert audit.changes["old_kickoff_utc"] == original.isoformat()


async def test_kickoff_unchanged_is_noop() -> None:
    kickoff = datetime(2026, 6, 15, 18, 0, 0)
    match = _make_match(status=MatchStatus.scheduled, kickoff=kickoff)
    fd = _fd_match(
        status=FDMatchStatus.TIMED,
        utc_date=kickoff.replace(tzinfo=UTC),
        home_score=None,
        away_score=None,
    )
    factory, session = _mock_session_factory([_scalars([match])])
    client_factory = _mock_client_factory([fd])

    count = await result_sync.sync_results(session_factory=factory, client_factory=client_factory)

    assert count == 0
    assert match.kickoff_utc == kickoff
    assert not [
        c
        for c in session.add.call_args_list
        if isinstance(c.args[0], AuditLog) and c.args[0].action_type != ActionType.sync_triggered
    ]


# ---------------------------------------------------------------------------
# Failure counter + admin alert
# ---------------------------------------------------------------------------


async def test_api_failure_increments_counter_and_writes_audit() -> None:
    # No admin profiles returned, so alert path inserts nothing for admins.
    factory, session = _mock_session_factory([_scalars([])])
    client_factory = _mock_client_factory(raise_error=FootballDataServerError("503: maintenance"))

    count = await result_sync.sync_results(session_factory=factory, client_factory=client_factory)

    assert count == 0
    audit = next(c.args[0] for c in session.add.call_args_list if isinstance(c.args[0], AuditLog))
    assert audit.action_type == ActionType.sync_failed
    assert audit.actor_type == ActorType.system


async def test_three_consecutive_failures_alerts_admins() -> None:
    err = FootballDataServerError("503")

    for _ in range(2):
        factory, _ = _mock_session_factory([_scalars([])])
        client_factory = _mock_client_factory(raise_error=err)
        await result_sync.sync_results(session_factory=factory, client_factory=client_factory)

    # Third failure should trigger notify_auto_sync_failed.
    factory, _ = _mock_session_factory([_scalars([])])
    client_factory = _mock_client_factory(raise_error=err)
    _alert_patch = "src.services.result_sync.notify_auto_sync_failed"
    with patch(_alert_patch, new_callable=AsyncMock) as mock_alert:
        await result_sync.sync_results(session_factory=factory, client_factory=client_factory)

    mock_alert.assert_awaited_once()
    assert "503" in mock_alert.call_args.args[1]


async def test_successful_sync_resets_failure_counter() -> None:
    # Fail twice, then succeed → counter back to 0.
    err = FootballDataServerError("503")
    for _ in range(2):
        factory, _ = _mock_session_factory([_scalars([])])
        client_factory = _mock_client_factory(raise_error=err)
        await result_sync.sync_results(session_factory=factory, client_factory=client_factory)

    factory, _ = _mock_session_factory([_scalars([])])
    client_factory = _mock_client_factory([])
    await result_sync.sync_results(session_factory=factory, client_factory=client_factory)

    # Now another failure should be the *first* in a new streak, not the third.
    factory, session = _mock_session_factory([_scalars([])])
    client_factory = _mock_client_factory(raise_error=err)
    await result_sync.sync_results(session_factory=factory, client_factory=client_factory)
    notifications = [
        c.args[0] for c in session.add.call_args_list if isinstance(c.args[0], NotificationLog)
    ]
    assert notifications == []


# ---------------------------------------------------------------------------
# Unknown match — silently skipped
# ---------------------------------------------------------------------------


async def test_unknown_fd_match_id_is_skipped() -> None:
    fd = _fd_match(status=FDMatchStatus.FINISHED)
    factory, session = _mock_session_factory([_scalars([]), _scalars([])])
    client_factory = _mock_client_factory([fd])

    count = await result_sync.sync_results(session_factory=factory, client_factory=client_factory)

    assert count == 0
    # No match-level audit rows for unknown matches (sync_triggered system row is expected).
    assert not [
        c
        for c in session.add.call_args_list
        if isinstance(c.args[0], AuditLog) and c.args[0].action_type != ActionType.sync_triggered
    ]


async def test_unknown_fd_match_id_backfills_ids_via_team_codes() -> None:
    home_team = _make_team(code="HOM")
    away_team = _make_team(code="AWY")
    match = _make_match(
        fd_id=None,
        status=MatchStatus.locked,
        stage=TournamentStage.group,
        home_team_id=home_team.id,
        away_team_id=away_team.id,
    )
    fd = _fd_match(
        fd_id=998877,
        status=FDMatchStatus.FINISHED,
        stage="GROUP_STAGE",
        home_team_id=11,
        away_team_id=22,
        home_tla="HOM",
        away_tla="AWY",
    )
    factory, _ = _mock_session_factory(
        [
            _scalars([]),
            _scalars([home_team, away_team]),
            _scalars([match]),
        ]
    )
    client_factory = _mock_client_factory([fd])

    count = await result_sync.sync_results(session_factory=factory, client_factory=client_factory)

    assert count == 1
    assert home_team.football_data_team_id == 11
    assert away_team.football_data_team_id == 22
    assert match.football_data_match_id == 998877
    assert match.actual_home_score == 2
    assert match.actual_away_score == 1
    assert match.status == MatchStatus.completed


# ---------------------------------------------------------------------------
# R6.6 — push failure does not block match commit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_push_failure_does_not_block_match_commit(caplog: pytest.LogCaptureFixture) -> None:
    """A raising notify provider must not prevent the match result from being committed."""
    match = _make_match(status=MatchStatus.locked)
    fd = _fd_match(status=FDMatchStatus.FINISHED, home_score=2, away_score=0)
    factory, session = _mock_session_factory([_scalars([match])])
    client_factory = _mock_client_factory([fd])

    with (
        patch(
            "src.services.result_sync.notify_result_detected",
            new_callable=AsyncMock,
            side_effect=Exception("push provider down"),
        ),
        patch("src.services.result_sync.notify_kickoff_changed", new_callable=AsyncMock),
        patch("src.services.result_sync.notify_match_postponed", new_callable=AsyncMock),
    ):
        import logging

        with caplog.at_level(logging.ERROR, logger="src.services.result_sync"):
            count = await result_sync.sync_results(
                session_factory=factory, client_factory=client_factory
            )

    # Match result was still applied and committed
    assert count == 1
    assert match.actual_home_score == 2
    assert match.actual_away_score == 0
    assert match.status == MatchStatus.completed
    session.commit.assert_awaited()

    # The notification failure stayed isolated to logging/observability.
    assert match.result_source == ResultSource.auto


# ---------------------------------------------------------------------------
# Auto-advance — knockout bracket resolves on the auto-fetch path (C-P0)
# ---------------------------------------------------------------------------


async def test_finished_result_triggers_knockout_bracket_sync(
    _no_bracket_sync: AsyncMock,
) -> None:
    """A settled result on the auto path resolves the next knockout round.

    Regression for the C-P0 where ``sync_results`` never called
    ``sync_knockout_bracket`` (only manual admin paths did), so R16+ fixtures
    stayed on TBD placeholders and could never be scored.
    """
    match = _make_match(status=MatchStatus.locked)
    fd = _fd_match(status=FDMatchStatus.FINISHED, home_score=2, away_score=1)
    factory, _ = _mock_session_factory([_scalars([match])])
    client_factory = _mock_client_factory([fd])

    count = await result_sync.sync_results(session_factory=factory, client_factory=client_factory)

    assert count == 1
    _no_bracket_sync.assert_awaited_once()


async def test_no_finished_result_skips_knockout_bracket_sync(
    _no_bracket_sync: AsyncMock,
) -> None:
    """A cycle with only kickoff drift (no settled result) leaves the bracket alone."""
    kickoff = datetime(2026, 6, 15, 18, 0, 0)
    new_kickoff = datetime(2026, 6, 15, 20, 0, 0)
    match = _make_match(status=MatchStatus.scheduled, kickoff=kickoff)
    fd = _fd_match(
        status=FDMatchStatus.TIMED,
        utc_date=new_kickoff.replace(tzinfo=UTC),
        home_score=None,
        away_score=None,
    )
    factory, _ = _mock_session_factory([_scalars([match])])
    client_factory = _mock_client_factory([fd])

    count = await result_sync.sync_results(session_factory=factory, client_factory=client_factory)

    assert count == 1
    _no_bracket_sync.assert_not_awaited()


# ---------------------------------------------------------------------------
# Scheduler registration
# ---------------------------------------------------------------------------


def test_scheduler_registers_5_minute_sync_job() -> None:
    from src.scheduler import create_scheduler

    scheduler = create_scheduler()
    try:
        job = scheduler.get_job("sync_results")
        assert job is not None
        assert job.trigger.interval == timedelta(minutes=5)
        assert job.coalesce is True
        assert job.max_instances == 1
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)
