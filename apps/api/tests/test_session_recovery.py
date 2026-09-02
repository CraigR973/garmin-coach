"""Batch 242 / CR236-01 — the recovery helper must never raise from a handler."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.profile import Profile, UserRole
from src.services.session_recovery import restore_after_rollback


@dataclass(frozen=True)
class _NotAnOrmObject:
    value: int


@pytest.mark.asyncio
async def test_none_and_non_orm_arguments_are_skipped_silently() -> None:
    """The call sites pass whatever the handler still holds.

    ``PreparedPostActivityRead`` in ``routers/daily_loop.py`` is a plain
    dataclass sitting right beside two real ORM instances, and
    ``sqlalchemy.inspect`` raises ``NoInspectionAvailable`` on it. A recovery
    helper that raises is worse than no recovery helper at all, because it
    raises from inside the ``except`` clause it was added to protect.
    """
    session = MagicMock()
    session.refresh = AsyncMock()

    await restore_after_rollback(session, None, _NotAnOrmObject(value=1), None)

    session.refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_failed_reload_is_logged_not_raised() -> None:
    """A row that did not survive the discarded transaction must not re-raise."""
    profile = MagicMock()
    logger = MagicMock()
    session = MagicMock()
    session.refresh = AsyncMock(side_effect=RuntimeError("row is gone"))

    with (
        patch("src.services.session_recovery.inspect", return_value=MagicMock(expired=True)),
        patch("src.services.session_recovery.log", logger),
    ):
        await restore_after_rollback(session, profile)

    session.refresh.assert_awaited_once_with(profile)
    logger.warning.assert_called_once()


@pytest.mark.asyncio
async def test_an_unexpired_instance_costs_no_io() -> None:
    """Safe to call at the top of every loop iteration, not only in a handler."""
    session = MagicMock()
    session.refresh = AsyncMock()

    with patch("src.services.session_recovery.inspect", return_value=MagicMock(expired=False)):
        await restore_after_rollback(session, MagicMock())

    session.refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_expired_instance_is_reloaded_against_a_real_session(
    db_conn: AsyncConnection,
) -> None:
    """The end-to-end shape, against a real AsyncSession and a real row.

    ``join_transaction_mode="create_savepoint"`` keeps the session's own
    transaction top-level — so ``rollback()`` still expires the whole identity
    map, exactly as in production — while unwinding only to a savepoint, so the
    seeded row survives to be reloaded. Without it the rollback discards the
    row the test just wrote and the reload has nothing to find, which is a state
    production is never in.
    """
    user_id = uuid.uuid4()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as seed:
        seed.add(
            Profile(
                id=user_id,
                display_name="Recovery",
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
            )
        )
        await seed.commit()

    async with AsyncSession(
        bind=db_conn,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    ) as session:
        profile = await session.get(Profile, user_id)
        assert profile is not None

        await session.rollback()
        assert inspect(profile).expired

        await restore_after_rollback(session, profile)

        assert not inspect(profile).expired
        assert profile.id == user_id
        assert profile.display_name == "Recovery"
