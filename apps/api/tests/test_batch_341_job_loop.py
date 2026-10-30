"""Batch 341 (CR327-04): the scheduler's per-profile loop, written once.

The last test drives it with a real ``AsyncSession`` and a step that writes and then
fails, which is how CR327-02 proved its two instances: an ``AsyncMock`` session never
expires anything, so a handler that reads a rolled-back profile passes with one.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import KnowledgeBase
from src.models.profile import Profile, UserRole
from src.services.job_loop import ProfileRef, for_each_active_profile


def _profile(timezone: str = "Europe/London") -> MagicMock:
    profile = MagicMock()
    profile.id = uuid.uuid4()
    profile.timezone = timezone
    return profile


@pytest.mark.asyncio
async def test_a_failure_rolls_back_runs_the_jobs_handler_and_moves_on() -> None:
    session = AsyncMock()
    first, second = _profile(), _profile()
    calls: list[tuple[str, Any]] = []

    async def step(_session: AsyncSession, profile: Profile, ref: ProfileRef) -> None:
        calls.append(("step", ref.id))
        if profile is first:
            raise RuntimeError("boom")

    async def on_failure(
        _session: AsyncSession, profile: Profile, ref: ProfileRef, exc: Exception
    ) -> None:
        calls.append(("failed", (ref.id, str(exc), session.rollback.await_count)))

    result = await for_each_active_profile(
        "test-job", step, session=session, profiles=[first, second], on_failure=on_failure
    )

    assert calls == [
        ("step", first.id),
        # The rollback happened before the handler ran.
        ("failed", (first.id, "boom", 1)),
        ("step", second.id),
    ]
    assert result.profiles == 2
    assert result.failed == [first.id]
    assert result.failures == 1


@pytest.mark.asyncio
async def test_the_subject_day_is_computed_once_per_profile_before_the_step() -> None:
    session = AsyncMock()
    profile = _profile()
    seen: list[ProfileRef] = []

    async def step(_session: AsyncSession, _profile: Profile, ref: ProfileRef) -> None:
        seen.append(ref)

    async def on_failure(*_args: Any) -> None:
        raise AssertionError("no failure expected")

    await for_each_active_profile(
        "test-job",
        step,
        session=session,
        profiles=[profile],
        on_failure=on_failure,
        today=lambda _p: date(2026, 11, 1),
    )

    assert seen == [ProfileRef(id=profile.id, timezone="Europe/London", today=date(2026, 11, 1))]


@pytest.mark.asyncio
async def test_a_failing_handler_still_escapes_as_it_did_before() -> None:
    """A failure path that fails is the job's failure, not something to swallow."""

    async def step(*_args: Any) -> None:
        raise RuntimeError("step")

    async def on_failure(*_args: Any) -> None:
        raise RuntimeError("handler")

    with pytest.raises(RuntimeError, match="handler"):
        await for_each_active_profile(
            "test-job",
            step,
            session=AsyncMock(),
            profiles=[_profile(), _profile()],
            on_failure=on_failure,
        )


@pytest.mark.asyncio
async def test_on_a_real_session_a_rolled_back_profile_is_usable_again(
    db_conn: AsyncConnection,
) -> None:
    """CR327-02's probe: a write, a failure, a rollback, then the profile is read again.

    Without the reloads, the handler's read of the first profile and the second step's
    read of the second both raise ``MissingGreenlet``: a top-level rollback expires
    every loaded instance.
    """
    async with AsyncSession(
        bind=db_conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
    ) as session:
        players = [
            Profile(
                id=uuid.uuid4(),
                display_name=f"Job Loop {index} {uuid.uuid4()}",
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
            )
            for index in range(2)
        ]
        session.add_all(players)
        await session.commit()
        handled: list[str] = []
        stepped: list[str] = []

        async def step(session: AsyncSession, profile: Profile, ref: ProfileRef) -> None:
            stepped.append(profile.display_name)
            if profile is players[0]:
                session.add(
                    KnowledgeBase(
                        user_id=ref.id,
                        section="job_loop_probe",
                        version=1,
                        is_active=True,
                        source="test",
                        content={},
                        updated_by_profile_id=ref.id,
                    )
                )
                await session.flush()
                raise RuntimeError("after a write")

        async def on_failure(
            _session: AsyncSession, profile: Profile, ref: ProfileRef, exc: Exception
        ) -> None:
            handled.append(profile.display_name)

        result = await for_each_active_profile(
            "test-job", step, session=session, profiles=players, on_failure=on_failure
        )

    assert result.failures == 1
    assert handled == [players[0].display_name]
    assert stepped == [players[0].display_name, players[1].display_name]
