"""Batch 335: a swap or move carries the planned ride, never another morning's easing.

The replays drive the real services through the shapes CR327-01 found in production:

* 8 Oct 2026: Mark approved Thursday's Red recovery substitution of a Sweet Spot, then
  swapped Thursday with Saturday. The 29-minute eased event went to Saturday under the
  58-minute Sweet Spot row, and Saturday's own morning could not replace it.
* 10 Oct: on Saturday he took Home's "Move it to Sunday"; the same event went on to Sunday.
* 1 → 2 Aug: a Red substitution approved on 1 Aug and moved to 2 Aug.

Only the services' existing surface is used here, so each test fails on the code before
this batch.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import Analysis, PlannedWorkout, WorkoutDeliveryProposal
from src.models.profile import Profile
from src.services.executable_coaching import ExecutableCoachingService
from src.services.verdict_scaling import adjust_ir_for_verdict
from src.services.workout_delivery import (
    STATUS_APPROVED,
    STATUS_PUSHED,
    build_intervals_payload,
    build_structured_workout_ir,
)
from tests.test_executable_coaching import _FakeIntervalsClient, _seed_profile

THU, FRI, SAT, SUN = date(2026, 10, 8), date(2026, 10, 9), date(2026, 10, 10), date(2026, 10, 11)

SWEET_SPOT = {
    "format": "bike",
    "steps": [
        {"label": "Warm-up", "minutes": 15, "target": "easy spin"},
        {"label": "Sweet spot", "minutes": 30, "target": "89% FTP"},
        {"label": "Cool-down", "minutes": 13, "target": "easy spin"},
    ],
}
EASY_Z2_45 = {
    "format": "bike",
    "steps": [{"label": "Easy Z2", "minutes": 45, "target": "60-65% FTP"}],
}
EASY_Z2_90 = {
    "format": "bike",
    "steps": [{"label": "Easy Z2", "minutes": 90, "target": "60-65% FTP"}],
}


def _row(
    user_id: uuid.UUID,
    day: date,
    *,
    title: str,
    structured: dict[str, Any],
    workout_type: str,
    minutes: int,
) -> PlannedWorkout:
    return PlannedWorkout(
        id=uuid.uuid4(),
        user_id=user_id,
        workout_date=day,
        version=1,
        title=title,
        workout_type=workout_type,
        status="planned",
        is_active=True,
        planned_duration_min=minutes,
        intensity_target=None,
        structured_workout=structured,
        source="test",
    )


def _sweet_spot(user_id: uuid.UUID, day: date) -> PlannedWorkout:
    return _row(
        user_id,
        day,
        title="Sweet Spot (1 × 30 min @ 89%)",
        structured=SWEET_SPOT,
        workout_type="bike_sweet_spot",
        minutes=58,
    )


def _easy_z2(user_id: uuid.UUID, day: date, *, long: bool = False) -> PlannedWorkout:
    return _row(
        user_id,
        day,
        title="Easy Z2",
        structured=EASY_Z2_90 if long else EASY_Z2_45,
        workout_type="bike_endurance",
        minutes=90 if long else 45,
    )


def _morning(user_id: uuid.UUID, day: date, verdict: str) -> Analysis:
    return Analysis(
        user_id=user_id,
        analysis_type="morning",
        subject_date=day,
        generated_at_utc=datetime(day.year, day.month, day.day, 8, 40),
        prompt_version="morning-analysis-test",
        verdict=verdict,
        context_packet={"verdict": {"status": verdict}},
        output_markdown=f"{verdict} verdict",
        raw_response={},
    )


async def _seed(db_conn: AsyncConnection, *rows: PlannedWorkout) -> uuid.UUID:
    user_id = rows[0].user_id
    await _seed_profile(db_conn, user_id)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add_all(rows)
        await session.commit()
    return user_id


async def _active(session: AsyncSession, user_id: uuid.UUID, day: date) -> PlannedWorkout:
    row = await session.scalar(
        select(PlannedWorkout)
        .where(
            PlannedWorkout.user_id == user_id,
            PlannedWorkout.workout_date == day,
            PlannedWorkout.is_active.is_(True),
        )
        .order_by(PlannedWorkout.version.desc())
        .limit(1)
    )
    assert row is not None
    return row


def _ride(ir: dict[str, Any]) -> tuple[str, str]:
    payload = build_intervals_payload(ir)
    return payload["name"], payload["description"]


async def _assert_plan_ride_on_zwift(
    session: AsyncSession, service: ExecutableCoachingService, user_id: uuid.UUID, day: date
) -> PlannedWorkout:
    """The day's event is its plan row's own ride, re-pointed at the row."""
    row = await _active(session, user_id, day)
    live = await service.rail.latest_delivered_for_workout(user_id, row.id)
    assert live is not None, f"no live event for {day}"
    assert live.workout_date == day
    ir = live.structured_workout_ir
    assert ir["origin"] == "as_planned", (day, ir.get("name"))
    plan = build_structured_workout_ir(row, ftp_watts=280)
    assert _ride(ir) == _ride(plan), day
    assert ir["plannedWorkoutId"] == str(row.id)
    assert ir["plannedWorkoutVersion"] == row.version
    return row


async def _approve_red(
    session: AsyncSession,
    service: ExecutableCoachingService,
    user: Profile,
    day: date,
    workout_id: uuid.UUID,
) -> None:
    morning = _morning(user.id, day, "Red")
    session.add(morning)
    await session.commit()
    proposed = await service.regenerate_for_verdict(user, day, analysis=morning)
    assert [p.structured_workout_ir["origin"] for p in proposed] == ["red_substitution"]
    approved = await service.approve_adjustment(user, planned_workout_id=workout_id)
    assert approved.structured_workout_ir["origin"] == "red_substitution"


@pytest.mark.asyncio
async def test_approve_then_swap_8_oct_carries_the_plan_and_frees_saturdays_morning(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    thursday = _sweet_spot(user_id, THU)
    saturday = _easy_z2(user_id, SAT)
    await _seed(db_conn, thursday, saturday)
    fake = _FakeIntervalsClient()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=fake)
        await service.reconcile_deliveries(user, start_date=THU, end_date=SAT)
        await _approve_red(session, service, user, THU, thursday.id)

        await service.swap_day(user, planned_workout_id=thursday.id, target_date=SAT)

        moved = await _assert_plan_ride_on_zwift(session, service, user_id, SAT)
        assert moved.title == "Sweet Spot (1 × 30 min @ 89%)"
        brought = await _assert_plan_ride_on_zwift(session, service, user_id, THU)
        assert brought.title == "Easy Z2"
        # One cloud write per moved event: the move carried the plan ride with it.
        sat_writes = [payload for _, payload in fake.updates if "2026-10-10" in str(payload)]
        assert [payload["name"] for payload in sat_writes] == ["Sweet Spot (1 × 30 min @ 89%)"]

        # Saturday's own morning now decides Saturday's ride (it could not before).
        saturday_morning = _morning(user_id, SAT, "Amber")
        session.add(saturday_morning)
        await session.commit()
        offered = await service.regenerate_for_verdict(user, SAT, analysis=saturday_morning)
        assert [p.planned_workout_id for p in offered] == [moved.id]
        assert offered[0].structured_workout_ir["origin"] == "amber_regeneration"


@pytest.mark.asyncio
async def test_approve_then_move_1_to_2_aug_shape(db_conn: AsyncConnection) -> None:
    friday, saturday = date(2026, 8, 1), date(2026, 8, 2)
    user_id = uuid.uuid4()
    ride = _sweet_spot(user_id, friday)
    await _seed(db_conn, ride)
    fake = _FakeIntervalsClient()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=fake)
        await service.reconcile_deliveries(user, start_date=friday, end_date=friday)
        await _approve_red(session, service, user, friday, ride.id)

        await service.swap_day(user, planned_workout_id=ride.id, target_date=saturday)

        await _assert_plan_ride_on_zwift(session, service, user_id, saturday)
        assert await service.rail.latest_delivered_for_date(user_id, friday) is None


@pytest.mark.asyncio
async def test_a_carried_easing_moved_on_10_to_11_oct_arrives_as_the_plan(
    db_conn: AsyncConnection,
) -> None:
    """The state the pre-335 swap left on Saturday, then Home's "Move it to Sunday"."""
    user_id = uuid.uuid4()
    saturday = _sweet_spot(user_id, SAT)
    sunday = _easy_z2(user_id, SUN, long=True)
    await _seed(db_conn, saturday, sunday)
    fake = _FakeIntervalsClient()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=fake)
        await service.reconcile_deliveries(user, start_date=SUN, end_date=SUN)
        # Thursday's approved Red substitution, carried to Saturday under the Sweet Spot.
        carried = adjust_ir_for_verdict(build_structured_workout_ir(saturday, ftp_watts=280), "Red")
        carried["workoutDate"] = SAT.isoformat()
        session.add(
            WorkoutDeliveryProposal(
                user_id=user_id,
                planned_workout_id=saturday.id,
                planned_workout_version=1,
                workout_date=SAT,
                provider="intervals_icu",
                status=STATUS_PUSHED,
                proposed_at_utc=datetime(2026, 10, 8, 9, 40),
                pushed_at_utc=datetime(2026, 10, 8, 10, 7),
                structured_workout_ir=carried,
                intervals_payload=build_intervals_payload(carried),
                zwo_xml="",
                intervals_event_id="121350345",
            )
        )
        session.add(_morning(user_id, SAT, "Amber"))
        await session.commit()

        await service.swap_day(user, planned_workout_id=saturday.id, target_date=SUN)

        on_sunday = await _assert_plan_ride_on_zwift(session, service, user_id, SUN)
        assert on_sunday.title == "Sweet Spot (1 × 30 min @ 89%)"
        await _assert_plan_ride_on_zwift(session, service, user_id, SAT)


@pytest.mark.asyncio
async def test_the_8_to_11_oct_sequence_ends_with_each_dates_plan_on_zwift(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    thursday = _sweet_spot(user_id, THU)
    saturday = _easy_z2(user_id, SAT)
    sunday = _easy_z2(user_id, SUN, long=True)
    await _seed(db_conn, thursday, saturday, sunday)
    fake = _FakeIntervalsClient()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=fake)
        await service.reconcile_deliveries(user, start_date=THU, end_date=SUN)

        # Thu 8 Oct: approve the Red substitution, then swap Thursday and Saturday.
        await _approve_red(session, service, user, THU, thursday.id)
        await service.swap_day(user, planned_workout_id=thursday.id, target_date=SAT)

        # Sat 10 Oct: Amber; he approves the eased Sweet Spot, then moves it to Sunday.
        saturday_morning = _morning(user_id, SAT, "Amber")
        session.add(saturday_morning)
        await session.commit()
        sweet_spot = await _active(session, user_id, SAT)
        await service.regenerate_for_verdict(user, SAT, analysis=saturday_morning)
        await service.approve_adjustment(user, planned_workout_id=sweet_spot.id)
        await service.swap_day(user, planned_workout_id=sweet_spot.id, target_date=SUN)

        thu = await _assert_plan_ride_on_zwift(session, service, user_id, THU)
        sat = await _assert_plan_ride_on_zwift(session, service, user_id, SAT)
        sun = await _assert_plan_ride_on_zwift(session, service, user_id, SUN)
        assert (thu.title, thu.planned_duration_min) == ("Easy Z2", 45)
        assert (sat.title, sat.planned_duration_min) == ("Easy Z2", 90)
        assert sun.title == "Sweet Spot (1 × 30 min @ 89%)"
        # Sunday's own morning is free to change Sunday's ride.
        assert await service._deliberately_acted(user_id, sun) is False


@pytest.mark.asyncio
async def test_his_own_edit_still_moves_with_the_session(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    thursday = _sweet_spot(user_id, THU)
    await _seed(db_conn, thursday)
    fake = _FakeIntervalsClient()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=fake)
        await service.reconcile_deliveries(user, start_date=THU, end_date=THU)
        await service.edit_today(
            user, planned_workout_id=thursday.id, duration_scale_pct=80, intensity_scale_pct=95
        )

        await service.swap_day(user, planned_workout_id=thursday.id, target_date=FRI)

        moved = await _active(session, user_id, FRI)
        live = await service.rail.latest_delivered_for_workout(user_id, moved.id)
        assert live is not None
        assert live.structured_workout_ir["origin"] == "manual_override"
        assert live.structured_workout_ir["adjustment"]["manualOverride"] == {
            "durationScalePct": 80,
            "intensityScalePct": 95,
            "basisTotalDurationSec": 58 * 60,
        }


@pytest.mark.asyncio
async def test_an_approved_change_is_approved_and_never_pushed_twice(
    db_conn: AsyncConnection,
) -> None:
    """335.2: the consumed proposal is ``approved``, and neither push path re-sends it."""
    user_id = uuid.uuid4()
    thursday = _sweet_spot(user_id, THU)
    await _seed(db_conn, thursday)
    fake = _FakeIntervalsClient()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=fake)
        await service.reconcile_deliveries(user, start_date=THU, end_date=THU)
        await _approve_red(session, service, user, THU, thursday.id)

        live = await service.rail.latest_delivered_for_workout(user_id, thursday.id)
        assert live is not None
        consumed = (
            (
                await session.execute(
                    select(WorkoutDeliveryProposal).where(
                        WorkoutDeliveryProposal.user_id == user_id,
                        WorkoutDeliveryProposal.id != live.id,
                        WorkoutDeliveryProposal.planned_workout_id == thursday.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(consumed) == 1
        assert consumed[0].status == STATUS_APPROVED
        assert consumed[0].approved_by_profile_id == user_id
        assert consumed[0].intervals_event_id is None
        assert consumed[0].structured_workout_ir["deliveredByProposalId"] == str(live.id)

        created_before = len(fake.payloads)
        noon = datetime(2026, 10, 8, 12, 0)
        assert await service.auto_push_due(user, now_utc=noon) == []
        sent = await service.send_today(user, planned_workout_id=thursday.id, now_utc=noon)
        assert sent.id == live.id
        assert len(fake.payloads) == created_before
