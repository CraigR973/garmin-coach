"""Tests for Batch 16 app-generated 13-week blocks.

Covers the acceptance pillars:
  1. Generation shape — structured, 13-week 2121 (2 build / 1 recovery, then
     wk12 taper / wk13 consolidation).
  2. VO2 progression rules — generated VO2 days use the 30/15 progression late.
  3. Refine-then-lock versioning — edits are preserved and the draft is versioned.
  4. Locked blocks feed the owned plan (active planned_workouts) and are
     deliverable via the Zwift rail.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import KnowledgeBase, PlanBlock, PlannedWorkout
from src.models.profile import Profile, UserRole
from src.services.block_generator import (
    BLOCK_LOCK_SOURCE,
    GENERATED_BLOCK_SECTION,
    BlockGeneratorService,
    block_label,
    generate_block_plan,
    next_cycle_start,
)
from src.services.vo2_progression import (
    VO2_PROTOCOL_30_30,
    VO2_PROTOCOL_RONNESTAD_30_15,
)
from src.services.workout_delivery import build_structured_workout_ir

START = date(2026, 8, 3)  # a Monday


# ---------------------------------------------------------------------------
# Pure-function tests (no DB)
# ---------------------------------------------------------------------------


def test_block_label_build_pairs_alternate() -> None:
    assert block_label(1, "build") == "Build1"
    assert block_label(2, "build") == "Build2"
    assert block_label(4, "build") == "Build1"
    assert block_label(5, "build") == "Build2"
    assert block_label(7, "build") == "Build1"
    assert block_label(8, "build") == "Build2"
    assert block_label(10, "build") == "Build1"
    assert block_label(11, "build") == "Build2"


def test_block_label_non_build() -> None:
    assert block_label(3, "recovery") == "Recovery"
    assert block_label(12, "taper") == "Taper"
    assert block_label(13, "consolidation") == "Consolidation"


def test_next_cycle_start_is_next_monday() -> None:
    # 2026-08-05 is a Wednesday; next cycle start is the following Monday.
    assert next_cycle_start(date(2026, 8, 5)) == date(2026, 8, 10)
    # From a Monday, still rolls to the next week's Monday.
    assert next_cycle_start(date(2026, 8, 3)) == date(2026, 8, 10)


def test_generate_block_plan_shape() -> None:
    plan = generate_block_plan(
        start_date=START,
        ftp_watts=290,
        athlete_name="Mark",
        generated_at_utc=datetime(2026, 7, 1, 6, 0, 0),
    )

    assert plan["status"] == "draft"
    assert plan["framework"] == "13-week 2121"
    assert plan["ftpWatts"] == 290
    assert plan["athleteName"] == "Mark"
    assert plan["lockedAtUtc"] is None
    assert plan["startDate"] == START.isoformat()
    assert plan["endDate"] == (START + timedelta(days=13 * 7 - 1)).isoformat()
    assert len(plan["weeks"]) == 13

    # Weeks are contiguous, one per 7 days, numbered 1..13.
    for i, week in enumerate(plan["weeks"], start=1):
        assert week["weekNumber"] == i
        assert week["startDate"] == (START + timedelta(days=(i - 1) * 7)).isoformat()
        assert week["endDate"] == (START + timedelta(days=(i - 1) * 7 + 6)).isoformat()
        assert week["workouts"]


def test_generate_block_plan_2121_block_types() -> None:
    plan = generate_block_plan(
        start_date=START,
        ftp_watts=280,
        athlete_name="Mark",
        generated_at_utc=datetime(2026, 7, 1, 6, 0, 0),
    )
    types = [w["blockType"] for w in plan["weeks"]]
    assert types == [
        "build",
        "build",
        "recovery",
        "build",
        "build",
        "recovery",
        "build",
        "build",
        "recovery",
        "build",
        "build",
        "taper",
        "consolidation",
    ]
    assert types.count("build") == 8
    assert types.count("recovery") == 3
    assert types.count("taper") == 1
    assert types.count("consolidation") == 1


def _vo2_protocol_for_week(plan: dict, week_number: int) -> str | None:
    week = next(w for w in plan["weeks"] if w["weekNumber"] == week_number)
    vo2 = next((w for w in week["workouts"] if w["workoutType"] == "bike_vo2"), None)
    assert vo2 is not None
    structured = vo2["structuredWorkout"]
    return structured.get("vo2Protocol")


def test_generated_vo2_days_use_progression() -> None:
    plan = generate_block_plan(
        start_date=START,
        ftp_watts=280,
        athlete_name="Mark",
        generated_at_utc=datetime(2026, 7, 1, 6, 0, 0),
    )
    # Early build weeks use 30/30; late build weeks (>=7) use Rønnestad 30/15.
    assert _vo2_protocol_for_week(plan, 1) == VO2_PROTOCOL_30_30
    assert _vo2_protocol_for_week(plan, 2) == VO2_PROTOCOL_30_30
    assert _vo2_protocol_for_week(plan, 4) == VO2_PROTOCOL_30_30
    assert _vo2_protocol_for_week(plan, 7) == VO2_PROTOCOL_RONNESTAD_30_15
    assert _vo2_protocol_for_week(plan, 8) == VO2_PROTOCOL_RONNESTAD_30_15
    assert _vo2_protocol_for_week(plan, 10) == VO2_PROTOCOL_RONNESTAD_30_15


# ---------------------------------------------------------------------------
# DB-backed tests
# ---------------------------------------------------------------------------


async def _seed_profile(db_conn: AsyncConnection, user_id: uuid.UUID) -> None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            Profile(
                id=user_id,
                display_name="Block Test",
                pin_hash="x" * 60,
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_generate_persists_draft(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        draft = await BlockGeneratorService(session).generate(user, start_date=START)
        assert draft["status"] == "draft"
        assert len(draft["weeks"]) == 13

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        kb = await session.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.user_id == user_id,
                KnowledgeBase.section == GENERATED_BLOCK_SECTION,
                KnowledgeBase.is_active.is_(True),
            )
        )
        assert kb is not None
        assert kb.content["status"] == "draft"
        assert kb.version == 1


@pytest.mark.asyncio
async def test_generate_twice_without_lock_conflicts(db_conn: AsyncConnection) -> None:
    from fastapi import HTTPException

    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = BlockGeneratorService(session)
        await service.generate(user, start_date=START)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = BlockGeneratorService(session)
        with pytest.raises(HTTPException) as exc_info:
            await service.generate(user, start_date=START)
        assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_refine_preserves_edit_and_versions(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        await BlockGeneratorService(session).generate(user, start_date=START)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        draft = await BlockGeneratorService(session).refine(
            user,
            week_number=1,
            day_offset=1,
            title="Custom VO2 Session",
            planned_duration_min=55,
        )
        week1 = next(w for w in draft["weeks"] if w["weekNumber"] == 1)
        edited = next(w for w in week1["workouts"] if w["dayOffset"] == 1)
        assert edited["title"] == "Custom VO2 Session"
        assert edited["plannedDurationMin"] == 55

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        # The active draft is now version 2, content carries the edit; an
        # archived version 1 still exists with the original title.
        active = await session.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.user_id == user_id,
                KnowledgeBase.section == GENERATED_BLOCK_SECTION,
                KnowledgeBase.is_active.is_(True),
            )
        )
        assert active is not None
        assert active.version == 2
        week1 = next(w for w in active.content["weeks"] if w["weekNumber"] == 1)
        edited = next(w for w in week1["workouts"] if w["dayOffset"] == 1)
        assert edited["title"] == "Custom VO2 Session"

        archived = await session.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.user_id == user_id,
                KnowledgeBase.section == GENERATED_BLOCK_SECTION,
                KnowledgeBase.version == 1,
            )
        )
        assert archived is not None
        assert archived.is_active is False
        old_week1 = next(w for w in archived.content["weeks"] if w["weekNumber"] == 1)
        old = next(w for w in old_week1["workouts"] if w["dayOffset"] == 1)
        assert old["title"] != "Custom VO2 Session"


@pytest.mark.asyncio
async def test_lock_writes_active_plan_and_preserves_refinement(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        await BlockGeneratorService(session).generate(user, start_date=START)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        await BlockGeneratorService(session).refine(
            user, week_number=1, day_offset=1, title="Refined VO2"
        )

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        result = await BlockGeneratorService(session).lock(user)
        assert result.blocks_created == 13
        assert result.workouts_written > 0
        assert result.start_date == START

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        # 13 plan blocks now exist.
        blocks = (
            (await session.execute(select(PlanBlock).where(PlanBlock.user_id == user_id)))
            .scalars()
            .all()
        )
        assert len(blocks) == 13

        # The refined VO2 day was written into the active plan.
        refined = await session.scalar(
            select(PlannedWorkout).where(
                PlannedWorkout.user_id == user_id,
                PlannedWorkout.workout_date == START + timedelta(days=1),
                PlannedWorkout.is_active.is_(True),
            )
        )
        assert refined is not None
        assert refined.title == "Refined VO2"
        assert refined.source == BLOCK_LOCK_SOURCE

        # The draft is now locked.
        kb = await session.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.user_id == user_id,
                KnowledgeBase.section == GENERATED_BLOCK_SECTION,
                KnowledgeBase.is_active.is_(True),
            )
        )
        assert kb is not None
        assert kb.content["status"] == "locked"
        assert kb.content["lockedAtUtc"] is not None


@pytest.mark.asyncio
async def test_lock_versions_existing_workout_on_same_date(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)

    # A pre-existing active workout sits on the block's first VO2 day.
    existing_date = START + timedelta(days=1)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            PlannedWorkout(
                user_id=user_id,
                workout_date=existing_date,
                version=1,
                title="Old Session",
                workout_type="bike_vo2",
                status="planned",
                is_active=True,
                planned_duration_min=60,
                intensity_target="x",
                structured_workout={"format": "bike", "steps": []},
                source="test",
            )
        )
        await session.commit()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = BlockGeneratorService(session)
        await service.generate(user, start_date=START)
        await service.lock(user)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        rows = (
            (
                await session.execute(
                    select(PlannedWorkout)
                    .where(
                        PlannedWorkout.user_id == user_id,
                        PlannedWorkout.workout_date == existing_date,
                    )
                    .order_by(PlannedWorkout.version.asc())
                )
            )
            .scalars()
            .all()
        )
        # Old version archived, new active version from the locked block.
        assert len(rows) == 2
        assert rows[0].version == 1 and rows[0].is_active is False
        assert rows[1].version == 2 and rows[1].is_active is True
        assert rows[1].source == BLOCK_LOCK_SOURCE


@pytest.mark.asyncio
async def test_locked_block_is_deliverable_via_zwift_rail(db_conn: AsyncConnection) -> None:
    """16.4 — a locked generated VO2 day converts to a deliverable Zwift IR."""
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = BlockGeneratorService(session)
        await service.generate(user, start_date=START)
        await service.lock(user)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        # Week 7 VO2 day (Rønnestad 30/15) — must flatten to deliverable steps.
        vo2 = await session.scalar(
            select(PlannedWorkout).where(
                PlannedWorkout.user_id == user_id,
                PlannedWorkout.workout_date == START + timedelta(days=6 * 7 + 1),
                PlannedWorkout.is_active.is_(True),
            )
        )
        assert vo2 is not None
        assert vo2.workout_type == "bike_vo2"
        ir = build_structured_workout_ir(vo2, ftp_watts=290)
        assert ir["steps"]
        assert ir["totalDurationSec"] > 0
        assert ir["ftpWatts"] == 290


@pytest.mark.asyncio
async def test_refine_after_lock_conflicts(db_conn: AsyncConnection) -> None:
    from fastapi import HTTPException

    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = BlockGeneratorService(session)
        await service.generate(user, start_date=START)
        await service.lock(user)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = BlockGeneratorService(session)
        with pytest.raises(HTTPException) as exc_info:
            await service.refine(user, week_number=1, day_offset=1, title="nope")
        assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_generate_allowed_after_lock(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = BlockGeneratorService(session)
        await service.generate(user, start_date=START)
        await service.lock(user)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        # A new block starting later is allowed once the prior draft is locked.
        draft = await BlockGeneratorService(session).generate(
            user, start_date=START + timedelta(days=13 * 7)
        )
        assert draft["status"] == "draft"


@pytest.mark.asyncio
async def test_discard_removes_unlocked_draft(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = BlockGeneratorService(session)
        await service.generate(user, start_date=START)
        await service.discard(user)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        active = await session.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.user_id == user_id,
                KnowledgeBase.section == GENERATED_BLOCK_SECTION,
                KnowledgeBase.is_active.is_(True),
            )
        )
        assert active is None
        # generate is allowed again after discard.
        user = await session.get(Profile, user_id)
        assert user is not None
        draft = await BlockGeneratorService(session).generate(user, start_date=START)
        assert draft["status"] == "draft"


@pytest.mark.asyncio
async def test_discard_locked_block_conflicts(db_conn: AsyncConnection) -> None:
    from fastapi import HTTPException

    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = BlockGeneratorService(session)
        await service.generate(user, start_date=START)
        await service.lock(user)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        with pytest.raises(HTTPException) as exc_info:
            await BlockGeneratorService(session).discard(user)
        assert exc_info.value.status_code == 409
