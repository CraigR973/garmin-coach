"""Batch 341 (CR327-05): the plan draft's writers are serialised.

Two writers raced the draft with no lock. Two changes at one revision both passed the
revision check, and then either the unique version index turned the second into a 500
or, timed differently, the second silently replaced the first. A decline landing between
a change's read and its write let the declined plan come back. Each test holds the
first writer open between its read and its write and lets a second writer run.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.models.coaching import KnowledgeBase, PlanBlock, PlannedWorkout
from src.models.profile import Profile, UserRole
from src.services.block_generator import PLAN_MOVED_ON_WORDS, BlockGeneratorService
from src.services.coach_policy import GENERATED_BLOCK_SECTION

#: Well in the past, so the default plan a fresh profile is seeded with never overlaps it.
DB_START = date(2026, 6, 1)


class _HeldBlockGenerator(BlockGeneratorService):
    """Stops between reading the draft and writing it until the test lets it go on."""

    def __init__(
        self, session: AsyncSession, *, holding: asyncio.Event, release: asyncio.Event
    ) -> None:
        super().__init__(session)
        self.holding = holding
        self.release = release

    async def _save_draft(
        self, user: Profile, content: dict[str, Any], existing: KnowledgeBase | None
    ) -> None:
        self.holding.set()
        await self.release.wait()
        await super()._save_draft(user, content, existing)


async def _seed(factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with factory() as session:
        await session.execute(text("SET search_path TO coach, public"))
        player = Profile(
            id=uuid.uuid4(),
            display_name="Plan Draft Lock",
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()
        session.add(
            KnowledgeBase(
                user_id=player.id,
                section="profile",
                version=1,
                is_active=True,
                source="test",
                content={"athleteName": "Mark", "ftpWatts": 280},
                updated_by_profile_id=player.id,
            )
        )
        await session.commit()
        await BlockGeneratorService(session).generate(player, start_date=DB_START)
        return player.id


async def _cleanup(factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID) -> None:
    async with factory() as session:
        await session.execute(text("SET search_path TO coach, public"))
        await session.execute(delete(PlannedWorkout).where(PlannedWorkout.user_id == user_id))
        await session.execute(delete(PlanBlock).where(PlanBlock.user_id == user_id))
        await session.execute(delete(KnowledgeBase).where(KnowledgeBase.user_id == user_id))
        await session.execute(delete(Profile).where(Profile.id == user_id))
        await session.commit()


async def _draft_rows(
    factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> list[tuple[int, bool, dict[str, Any]]]:
    async with factory() as session:
        await session.execute(text("SET search_path TO coach, public"))
        rows = (
            await session.execute(
                select(KnowledgeBase)
                .where(
                    KnowledgeBase.user_id == user_id,
                    KnowledgeBase.section == GENERATED_BLOCK_SECTION,
                )
                .order_by(KnowledgeBase.version)
            )
        ).scalars()
        return [(row.version, row.is_active, dict(row.content)) for row in rows]


async def _race(
    factory: async_sessionmaker[AsyncSession],
    user_id: uuid.UUID,
    first: Callable[[BlockGeneratorService, Profile], Awaitable[Any]],
    second: Callable[[BlockGeneratorService, Profile], Awaitable[Any]],
) -> tuple[Any, BaseException | Any]:
    """Run ``first`` up to its write, start ``second``, then let ``first`` finish."""
    holding, release = asyncio.Event(), asyncio.Event()

    async def _run(
        build: Callable[[AsyncSession], BlockGeneratorService],
        step: Callable[[BlockGeneratorService, Profile], Awaitable[Any]],
    ) -> Any:
        async with factory() as session:
            await session.execute(text("SET search_path TO coach, public"))
            player = await session.get(Profile, user_id)
            assert player is not None
            return await step(build(session), player)

    first_task = asyncio.create_task(
        _run(lambda s: _HeldBlockGenerator(s, holding=holding, release=release), first)
    )
    await asyncio.wait_for(holding.wait(), timeout=5)
    second_task = asyncio.create_task(_run(BlockGeneratorService, second))
    # Long enough for the second writer to reach its read (and, since Batch 341, the lock).
    await asyncio.sleep(0.5)
    release.set()
    first_result = await asyncio.wait_for(first_task, timeout=10)
    second_outcome: BaseException | Any
    try:
        second_outcome = await asyncio.wait_for(second_task, timeout=10)
    except HTTPException as refused:
        second_outcome = refused
    return first_result, second_outcome


@pytest.mark.asyncio
async def test_two_changes_at_one_revision_are_a_409_not_a_500_or_a_lost_change(
    db_engine: AsyncEngine,
) -> None:
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    user_id = await _seed(factory)
    try:
        first, second = await _race(
            factory,
            user_id,
            lambda service, player: service.change(
                player, {"kind": "remove", "session": "s012"}, expected_revision=0
            ),
            lambda service, player: service.change(
                player, {"kind": "remove", "session": "s011"}, expected_revision=0
            ),
        )
        rows = await _draft_rows(factory, user_id)
    finally:
        await _cleanup(factory, user_id)

    assert first["revision"] == 1
    assert isinstance(second, HTTPException)
    assert (second.status_code, second.detail) == (409, PLAN_MOVED_ON_WORDS)
    # Exactly the first change, once: no lost write and no second version from the race.
    assert [(version, active) for version, active, _ in rows] == [(1, False), (2, True)]
    ids = [w["id"] for week in rows[-1][2]["weeks"] for w in week["workouts"]]
    assert "s012" not in ids
    assert "s011" in ids


@pytest.mark.asyncio
async def test_a_decline_during_a_change_keeps_the_plan_declined(db_engine: AsyncEngine) -> None:
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    user_id = await _seed(factory)
    try:
        await _race(
            factory,
            user_id,
            lambda service, player: service.change(player, {"kind": "remove", "session": "s012"}),
            lambda service, player: service.discard(player),
        )
        rows = await _draft_rows(factory, user_id)
    finally:
        await _cleanup(factory, user_id)

    # The change landed first and the decline after it: nothing is left waiting.
    assert [active for _, active, _ in rows] == [False, False]
