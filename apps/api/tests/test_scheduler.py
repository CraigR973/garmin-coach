"""Unit tests for the match-lock scheduler job."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.match import Match, MatchStatus
from src.models.notification import ActionType, ActorType, AuditLog
from src.scheduler import create_scheduler, lock_due_matches, run_scheduled_backup


@pytest.fixture(autouse=True)
def _no_notify_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    with patch("src.scheduler.notify_match_locked", new_callable=AsyncMock):
        yield


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _make_match(
    *,
    status: MatchStatus = MatchStatus.scheduled,
    kickoff: datetime | None = None,
) -> Match:
    m = MagicMock(spec=Match)
    m.id = uuid.uuid4()
    m.status = status
    m.kickoff_utc = kickoff or _now()
    m.locked_at = None
    m.deleted_at = None
    return m


def _scalars(items: list[Match]) -> MagicMock:
    r = MagicMock()
    r.scalars.return_value.all.return_value = items
    return r


def _mock_session_factory(execute_results: list) -> AsyncMock:
    """Build a session_factory that returns an async-context-manager session."""
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=execute_results)
    session.add = MagicMock()
    session.commit = AsyncMock()

    class _Ctx:
        async def __aenter__(self) -> AsyncMock:
            return session

        async def __aexit__(self, *a: object) -> None:
            return None

    factory = MagicMock(return_value=_Ctx())
    factory._session = session  # type: ignore[attr-defined]
    return factory


# ---------------------------------------------------------------------------
# lock_due_matches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lock_due_matches_locks_each_returned_match() -> None:
    now = _now()
    m1 = _make_match(kickoff=now - timedelta(minutes=5))
    m2 = _make_match(kickoff=now)
    factory = _mock_session_factory([_scalars([m1, m2])])

    count = await lock_due_matches(session_factory=factory, now=now)

    assert count == 2
    assert m1.status == MatchStatus.locked
    assert m1.locked_at == now
    assert m2.status == MatchStatus.locked
    assert m2.locked_at == now
    assert factory._session.commit.await_count >= 1


@pytest.mark.asyncio
async def test_lock_due_matches_writes_audit_row_per_lock() -> None:
    now = _now()
    m = _make_match(kickoff=now - timedelta(seconds=10))
    factory = _mock_session_factory([_scalars([m])])

    await lock_due_matches(session_factory=factory, now=now)

    added = [call.args[0] for call in factory._session.add.call_args_list]
    audit_rows = [a for a in added if isinstance(a, AuditLog)]
    assert len(audit_rows) == 1
    row = audit_rows[0]
    assert row.actor_id is None
    assert row.actor_type == ActorType.system
    assert row.action_type == ActionType.predictions_locked
    assert row.target_table == "matches"
    assert row.target_id == m.id


@pytest.mark.asyncio
async def test_lock_due_matches_no_matches_skips_commit() -> None:
    factory = _mock_session_factory([_scalars([])])

    count = await lock_due_matches(session_factory=factory, now=_now())

    assert count == 0
    factory._session.commit.assert_not_awaited()
    factory._session.add.assert_not_called()


@pytest.mark.asyncio
async def test_lock_due_matches_uses_provided_clock() -> None:
    """The function applies `now` to every lock_at, not wall-clock time."""
    fixed = datetime(2026, 6, 11, 16, 0, 0)
    m = _make_match(kickoff=fixed)
    factory = _mock_session_factory([_scalars([m])])

    await lock_due_matches(session_factory=factory, now=fixed)

    assert m.locked_at == fixed


# ---------------------------------------------------------------------------
# create_scheduler
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# run_scheduled_backup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_scheduled_backup_failure_writes_audit_and_notifies() -> None:
    """When create_backup raises, an audit row is written and notify_backup_failed is called."""
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()

    class _Ctx:
        async def __aenter__(self) -> AsyncMock:
            return session

        async def __aexit__(self, *a: object) -> None:
            return None

    with (
        patch(
            "src.scheduler.create_backup",
            new_callable=AsyncMock,
            side_effect=RuntimeError("pg_dump not found"),
        ),
        patch("src.scheduler.AsyncSessionLocal", return_value=_Ctx()),
        patch("src.scheduler.notify_backup_failed", new_callable=AsyncMock) as mock_notify,
    ):
        await run_scheduled_backup()

    added = [call.args[0] for call in session.add.call_args_list]
    audit_rows = [a for a in added if isinstance(a, AuditLog)]
    assert len(audit_rows) == 1
    row = audit_rows[0]
    assert row.action_type == ActionType.backup_failed
    assert row.actor_type == ActorType.system
    assert "pg_dump not found" in row.changes["error"]
    mock_notify.assert_awaited_once()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_scheduled_backup_notify_failure_does_not_raise() -> None:
    """If notify_backup_failed itself raises, the audit row is still committed."""
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()

    class _Ctx:
        async def __aenter__(self) -> AsyncMock:
            return session

        async def __aexit__(self, *a: object) -> None:
            return None

    with (
        patch(
            "src.scheduler.create_backup",
            new_callable=AsyncMock,
            side_effect=RuntimeError("disk full"),
        ),
        patch("src.scheduler.AsyncSessionLocal", return_value=_Ctx()),
        patch(
            "src.scheduler.notify_backup_failed",
            new_callable=AsyncMock,
            side_effect=Exception("push failed"),
        ),
    ):
        # Must not propagate any exception
        await run_scheduled_backup()

    session.commit.assert_awaited_once()


def test_create_scheduler_registers_fifteen_second_lock_job() -> None:
    scheduler = create_scheduler()
    try:
        job = scheduler.get_job("lock_due_matches")
        assert job is not None
        # Interval trigger fields expose `interval` as a timedelta.
        assert job.trigger.interval == timedelta(seconds=15)
        assert job.coalesce is True
        assert job.max_instances == 1
        assert scheduler.get_job("pick_confirmations") is not None
        digest = scheduler.get_job("daily_prediction_digest")
        assert digest is not None
        assert str(digest.trigger) == "cron[hour='9', minute='0']"
    finally:
        # Scheduler is not started by create_scheduler; nothing to shut down.
        if scheduler.running:
            scheduler.shutdown(wait=False)


# ---------------------------------------------------------------------------
# Lifespan integration — scheduler starts/stops cleanly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scheduler_lifespan_starts_and_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lifespan context starts the scheduler when enabled and registers the lock job."""
    import asyncio

    from src.config import settings
    from src.main import app, lifespan

    monkeypatch.setattr(settings, "scheduler_enabled", True)

    async with lifespan(app):
        scheduler = app.state.scheduler
        assert scheduler.running is True
        assert scheduler.get_job("lock_due_matches") is not None

    # AsyncIOScheduler shutdown finalises on the next loop tick.
    await asyncio.sleep(0)
    assert scheduler.running is False


@pytest.mark.asyncio
async def test_scheduler_lifespan_disabled_skips_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """When scheduler_enabled is False the scheduler is created but never started."""
    from src.config import settings
    from src.main import app, lifespan

    monkeypatch.setattr(settings, "scheduler_enabled", False)

    async with lifespan(app):
        assert app.state.scheduler.running is False
