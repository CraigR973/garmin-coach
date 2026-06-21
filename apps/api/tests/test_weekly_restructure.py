"""Tests for Batch 14 dynamic weekly restructuring.

Covers the four acceptance pillars: the no-stack rule, defer-on-fatigue, the
Rønnestad 30/15 emission, and versioned + approval-gated delivery.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import (
    Analysis,
    PlanBlock,
    PlannedWorkout,
    WorkoutDeliveryProposal,
)
from src.models.profile import Profile, UserRole
from src.services.vo2_progression import (
    VO2_PROTOCOL_30_30,
    VO2_PROTOCOL_RONNESTAD_30_15,
    build_vo2_structured_workout,
    select_vo2_protocol,
)
from src.services.weekly_restructure import (
    AUDIT_TYPE_RESTRUCTURE,
    WeekItem,
    WeeklyRestructureService,
    plan_week_restructure,
)
from src.services.workout_delivery import IntervalsCreateResult

# Week of Monday 2026-06-22.
WEEK_START = date(2026, 6, 22)
MON = WEEK_START
TUE = date(2026, 6, 23)
WED = date(2026, 6, 24)
THU = date(2026, 6, 25)
SAT = date(2026, 6, 27)


def _item(workout_date: date, workout_type: str, *, title: str = "") -> WeekItem:
    return WeekItem(
        workout_id=uuid.uuid4(),
        workout_date=workout_date,
        title=title or workout_type,
        workout_type=workout_type,
    )


# ---------------------------------------------------------------------------
# 14.1 — no-stack rule (pure engine)
# ---------------------------------------------------------------------------


def test_no_stack_separates_adjacent_vo2_and_sweet_spot() -> None:
    strength = _item(MON, "strength_recovery")
    vo2 = _item(TUE, "bike_vo2")
    sweet = _item(WED, "bike_sweet_spot")
    endurance = _item(SAT, "bike_endurance")

    plan = plan_week_restructure(
        [strength, vo2, sweet, endurance], week_start=WEEK_START, fatigued=False
    )

    assert plan.conflicts_before == [(TUE, WED)]
    assert plan.conflicts_after == []
    assert plan.changed
    # The two hard sessions end up at least two days apart.
    vo2_date = next(d for d, wid in plan.assignment.items() if wid == vo2.workout_id)
    sweet_date = next(d for d, wid in plan.assignment.items() if wid == sweet.workout_id)
    assert abs((vo2_date - sweet_date).days) >= 2
    assert all(change.reason == "no_stack" for change in plan.changes)


def test_no_change_when_already_spaced_and_fresh() -> None:
    plan = plan_week_restructure(
        [
            _item(MON, "strength_recovery"),
            _item(TUE, "bike_vo2"),
            _item(THU, "bike_sweet_spot"),
            _item(SAT, "bike_endurance"),
        ],
        week_start=WEEK_START,
        fatigued=False,
    )

    assert plan.conflicts_before == []
    assert plan.changes == []
    assert not plan.changed


# ---------------------------------------------------------------------------
# 14.2 — defer-on-fatigue (pure engine)
# ---------------------------------------------------------------------------


def test_fatigue_defers_hard_session_later_in_week() -> None:
    vo2 = _item(TUE, "bike_vo2")
    endurance = _item(SAT, "bike_endurance")
    items = [_item(MON, "strength_recovery"), vo2, endurance]

    fresh = plan_week_restructure(items, week_start=WEEK_START, fatigued=False)
    assert fresh.changes == []  # no spacing conflict, nothing to do when fresh

    fatigued = plan_week_restructure(items, week_start=WEEK_START, fatigued=True)
    # The VO2 session is pushed to the later slot; the easy ride moves earlier.
    vo2_date = next(d for d, wid in fatigued.assignment.items() if wid == vo2.workout_id)
    assert vo2_date == SAT
    assert any(
        change.reason == "defer_fatigue" and change.to_workout_id == vo2.workout_id
        for change in fatigued.changes
    )


# ---------------------------------------------------------------------------
# 14.3 — Rønnestad 30/15 emission (toolkit)
# ---------------------------------------------------------------------------


def test_late_build_week_selects_ronnestad_30_15() -> None:
    early = select_vo2_protocol(3, block_type="build")
    late = select_vo2_protocol(7, block_type="build")

    assert early.key == VO2_PROTOCOL_30_30
    assert late.key == VO2_PROTOCOL_RONNESTAD_30_15

    structured = build_vo2_structured_workout(7, block_type="build")
    assert structured["vo2Protocol"] == VO2_PROTOCOL_RONNESTAD_30_15
    assert structured["ergMode"] == "off"  # surge lag → ERG off (Decision #33)
    main = next(s for s in structured["steps"] if s["label"] == "Main set")
    assert main["pattern"] == "13x 30s on / 15s easy"
    assert main["target"] == "105-110% FTP"


def test_early_build_week_keeps_30_30() -> None:
    structured = build_vo2_structured_workout(3, block_type="build")
    assert structured["vo2Protocol"] == VO2_PROTOCOL_30_30
    main = next(s for s in structured["steps"] if s["label"] == "Main set")
    assert main["pattern"] == "5x 30s on / 30s off"


# ---------------------------------------------------------------------------
# DB-backed: recovery signal, versioning, delivery, 30/15 integration
# ---------------------------------------------------------------------------


class _FakeIntervalsClient:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    async def create_workout_event(self, payload: dict) -> IntervalsCreateResult:
        self.payloads.append(payload)
        return IntervalsCreateResult(event_id="evt_1", raw_response={"id": "evt_1"})


async def _seed_profile(db_conn: AsyncConnection, user_id: uuid.UUID) -> None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            Profile(
                id=user_id,
                display_name="Restructure Test",
                pin_hash="x" * 60,
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
            )
        )
        await session.commit()


def _planned(
    user_id: uuid.UUID,
    workout_date: date,
    workout_type: str,
    title: str,
    structured: dict,
    *,
    plan_block_id: uuid.UUID | None = None,
    intensity: str = "",
) -> PlannedWorkout:
    return PlannedWorkout(
        id=uuid.uuid4(),
        user_id=user_id,
        plan_block_id=plan_block_id,
        workout_date=workout_date,
        version=1,
        title=title,
        workout_type=workout_type,
        status="planned",
        is_active=True,
        planned_duration_min=60,
        intensity_target=intensity or title,
        structured_workout=structured,
        source="test",
    )


_VO2 = {
    "format": "bike",
    "steps": [
        {"label": "Warm-up", "minutes": 15, "target": "easy spin"},
        {
            "label": "Main set",
            "repeats": 3,
            "pattern": "5x 30s on / 30s off",
            "target": "105-110% FTP",
        },
        {"label": "Cool-down", "minutes": 10, "target": "easy spin"},
    ],
}
_SWEET = {
    "format": "bike",
    "steps": [
        {"label": "Warm-up", "minutes": 15, "target": "easy spin"},
        {
            "label": "Main set",
            "repeats": 3,
            "pattern": "8 min on / 4 min easy",
            "target": "88-94% FTP",
        },
        {"label": "Cool-down", "minutes": 10, "target": "easy spin"},
    ],
}
_ENDURANCE = {
    "format": "bike",
    "steps": [{"label": "Main ride", "minutes": 90, "target": "Zone 2"}],
}


@pytest.mark.asyncio
async def test_assess_recovery_signal_flags_red_verdict(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            Analysis(
                user_id=user_id,
                analysis_type="morning",
                subject_date=TUE,
                generated_at_utc=datetime(2026, 6, 23, 6, 30),
                prompt_version="morning-test",
                verdict="Red",
                context_packet={},
                output_markdown="Red",
                raw_response={},
            )
        )
        await session.commit()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = WeeklyRestructureService(session)
        signal = await service.assess_recovery_signal(user, as_of=TUE)
        assert signal.fatigued is True
        assert "Red" in signal.recent_verdicts


@pytest.mark.asyncio
async def test_assess_recovery_signal_fresh_when_no_data(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = WeeklyRestructureService(session)
        signal = await service.assess_recovery_signal(user, as_of=TUE)
        assert signal.fatigued is False
        assert signal.reasons == []


@pytest.mark.asyncio
async def test_apply_versions_changed_days_and_proposes_delivery(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    vo2 = _planned(user_id, TUE, "bike_vo2", "VO2 Max 30/30", _VO2)
    sweet = _planned(user_id, WED, "bike_sweet_spot", "Sweet Spot Builder", _SWEET)
    endurance = _planned(user_id, SAT, "bike_endurance", "Long Endurance Ride", _ENDURANCE)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add_all([vo2, sweet, endurance])
        await session.commit()

    fake = _FakeIntervalsClient()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = WeeklyRestructureService(session, intervals_client=fake)

        result = await service.apply_for_week(user, WEEK_START, as_of=TUE)

        assert result.plan.changed
        assert result.plan.conflicts_after == []
        # Changed dates got a new active version; proposals are gated (not pushed).
        assert result.versioned_workouts
        assert all(p.status == "proposed" for p in result.proposals)
        assert fake.payloads == []  # nothing reaches Zwift without approval

        # VO2 stays on Tuesday; Sweet-Spot was pushed away to ≥2 days from it.
        active = (
            (
                await session.execute(
                    select(PlannedWorkout).where(
                        PlannedWorkout.user_id == user_id,
                        PlannedWorkout.is_active.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        by_date = {w.workout_date: w for w in active}
        assert by_date[TUE].workout_type == "bike_vo2"
        sweet_date = next(d for d, w in by_date.items() if w.workout_type == "bike_sweet_spot")
        assert abs((sweet_date - TUE).days) >= 2
        # The moved day is a fresh version, source-stamped.
        moved = by_date[sweet_date]
        assert moved.version == 2
        assert moved.source == "weekly_restructure"

        audit = (
            (
                await session.execute(
                    select(Analysis).where(Analysis.analysis_type == AUDIT_TYPE_RESTRUCTURE)
                )
            )
            .scalars()
            .all()
        )
        assert len(audit) == 1
        assert audit[0].subject_date == WEEK_START

        # Idempotent: the settled week needs no further changes.
        again = await service.apply_for_week(user, WEEK_START, as_of=TUE)
        assert again.plan.changes == []
        assert again.versioned_workouts == []


@pytest.mark.asyncio
async def test_apply_regenerates_deferred_late_build_vo2_as_ronnestad(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    block_id = uuid.uuid4()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            PlanBlock(
                id=block_id,
                user_id=user_id,
                name="Week 07 Build",
                version=1,
                sequence_index=7,
                block_type="build",
                start_date=WEEK_START,
                end_date=SAT,
                goals_json={},
                raw_plan={},
            )
        )
        session.add_all(
            [
                _planned(user_id, TUE, "bike_vo2", "VO2 Max 30/30", _VO2, plan_block_id=block_id),
                _planned(
                    user_id,
                    SAT,
                    "bike_endurance",
                    "Long Endurance Ride",
                    _ENDURANCE,
                    plan_block_id=block_id,
                ),
            ]
        )
        # Fatigue trigger: a Red morning verdict in the trend window.
        session.add(
            Analysis(
                user_id=user_id,
                analysis_type="morning",
                subject_date=TUE,
                generated_at_utc=datetime(2026, 6, 23, 6, 30),
                prompt_version="morning-test",
                verdict="Red",
                context_packet={},
                output_markdown="Red",
                raw_response={},
            )
        )
        await session.commit()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = WeeklyRestructureService(session, intervals_client=_FakeIntervalsClient())

        result = await service.apply_for_week(user, WEEK_START, as_of=TUE)

        assert result.signal.fatigued is True
        active = (
            (
                await session.execute(
                    select(PlannedWorkout).where(
                        PlannedWorkout.user_id == user_id,
                        PlannedWorkout.is_active.is_(True),
                        PlannedWorkout.workout_type == "bike_vo2",
                    )
                )
            )
            .scalars()
            .one()
        )
        # Deferred to Saturday and regenerated through the late-build toolkit.
        assert active.workout_date == SAT
        assert active.structured_workout["vo2Protocol"] == VO2_PROTOCOL_RONNESTAD_30_15
        assert active.structured_workout["ergMode"] == "off"


@pytest.mark.asyncio
async def test_proposals_query_unused(db_conn: AsyncConnection) -> None:
    # Sanity: no proposals exist for a freshly seeded, no-op week.
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add_all(
            [
                _planned(user_id, TUE, "bike_vo2", "VO2 Max 30/30", _VO2),
                _planned(user_id, THU, "bike_sweet_spot", "Sweet Spot Builder", _SWEET),
            ]
        )
        await session.commit()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = WeeklyRestructureService(session, intervals_client=_FakeIntervalsClient())
        result = await service.apply_for_week(user, WEEK_START, as_of=TUE)
        assert result.plan.changes == []
        proposals = (await session.execute(select(WorkoutDeliveryProposal))).scalars().all()
        assert proposals == []
