"""Batch 335: what Zwift holds, read against the day, and the daily check that keeps it so.

* ``classify_live_ride`` says whether the ride on Zwift is the plan row's, a change made
  for this day, or neither, comparing rides as Zwift holds them (never the stored FTP).
* The daily check re-pushes a ride that is neither, and touches nothing else.
* Home and Week get the live ride; the morning's swap offer and week mix follow the live
  rows (UX333-02), and so does the state-change alert's today side.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import Analysis, KnowledgeBase, WorkoutDeliveryProposal
from src.models.profile import Profile
from src.services.daily_loop import DailyLoopService
from src.services.daily_loop_envelope import _serialize_analysis, _with_live_offers
from src.services.executable_coaching import AUDIT_TYPE_REPLACED, ExecutableCoachingService
from src.services.job_runs import JobStatus
from src.services.live_ride import (
    LIVE_RIDE_AS_PLANNED,
    LIVE_RIDE_CHANGED,
    LIVE_RIDE_NOT_THIS_DAY,
    LiveRideReader,
    classify_live_ride,
)
from src.services.state_change_coach import StateChangeCoachService
from src.services.verdict_scaling import (
    MORNING_TRANSFORM_ORIGINS,
    TRANSFORM_SHORTER,
    TRANSFORM_TIRED_TEMPO,
    TRANSFORM_TIRED_ZONE2,
    adjust_ir_for_verdict,
)
from src.services.weekly_mix import WeeklyMixService
from src.services.workout_delivery import (
    STATUS_PUSHED,
    build_intervals_payload,
    build_structured_workout_ir,
)
from tests.test_batch_335_swap_replay import (
    FRI,
    SAT,
    SUN,
    THU,
    _active,
    _easy_z2,
    _morning,
    _seed,
    _sweet_spot,
)
from tests.test_executable_coaching import _FakeIntervalsClient
from tests.test_scheduler import _session_ctx


def _plan(row: Any) -> dict[str, Any]:
    return build_structured_workout_ir(row, ftp_watts=280)


# -- the classification, pure ----------------------------------------------------------


def test_the_plan_ride_is_as_planned_even_after_an_ftp_change() -> None:
    row = _sweet_spot(uuid.uuid4(), SAT)
    live = _plan(row)
    live["origin"] = "as_planned"
    # 20 Oct 2026: profile FTP 280 -> 267; every pushed event still records 280.
    plan_now = build_structured_workout_ir(row, ftp_watts=267)
    assert live != plan_now
    assert classify_live_ride(live, plan_ir=plan_now, this_day=[]) == LIVE_RIDE_AS_PLANNED


def test_another_days_easing_is_not_this_days_ride() -> None:
    row = _sweet_spot(uuid.uuid4(), SAT)
    carried = adjust_ir_for_verdict(_plan(row), "Red")
    assert carried["origin"] == "red_substitution"
    assert classify_live_ride(carried, plan_ir=_plan(row), this_day=[]) == LIVE_RIDE_NOT_THIS_DAY
    graded = adjust_ir_for_verdict(_plan(row), "Amber", graded=True)
    assert graded["origin"] == "graded_amber_ease"
    assert classify_live_ride(graded, plan_ir=_plan(row), this_day=[]) == LIVE_RIDE_NOT_THIS_DAY


def test_this_days_own_easing_is_a_change_for_the_day() -> None:
    row = _sweet_spot(uuid.uuid4(), THU)
    eased = adjust_ir_for_verdict(_plan(row), "Red")
    assert classify_live_ride(eased, plan_ir=_plan(row), this_day=[eased]) == LIVE_RIDE_CHANGED


def test_his_own_edit_is_a_change_and_a_stale_baseline_is_not_this_days() -> None:
    row = _sweet_spot(uuid.uuid4(), THU)
    edited = _plan(row)
    edited["origin"] = "manual_override"
    edited["steps"] = [dict(step, durationSec=60) for step in edited["steps"]]
    assert classify_live_ride(edited, plan_ir=_plan(row), this_day=[]) == LIVE_RIDE_CHANGED
    stale = _plan(_easy_z2(row.user_id, THU))
    stale["origin"] = "as_planned"
    assert classify_live_ride(stale, plan_ir=_plan(row), this_day=[]) == LIVE_RIDE_NOT_THIS_DAY


def test_every_origin_a_morning_writes_is_a_morning_transform() -> None:
    """The set 335.1 corrected: the pre-296 list missed the graded engine's origins."""
    rows = [_sweet_spot(uuid.uuid4(), THU), _easy_z2(uuid.uuid4(), THU, long=True)]
    origins = set()
    for row in rows:
        for transform in ("Amber", "Red", TRANSFORM_TIRED_ZONE2, TRANSFORM_TIRED_TEMPO):
            for graded in (False, True):
                for companion in (False, True):
                    origins.add(
                        adjust_ir_for_verdict(
                            _plan(row), transform, companion_session=companion, graded=graded
                        )["origin"]
                    )
        origins.add(adjust_ir_for_verdict(_plan(row), TRANSFORM_SHORTER, graded=True)["origin"])
    origins.discard("as_planned")
    assert origins <= MORNING_TRANSFORM_ORIGINS
    assert {"graded_amber_ease", "graded_offer_shorter", "red_substitution"} <= origins


# -- the daily check and the restore, on Postgres --------------------------------------


async def _carried_red_on(
    session: AsyncSession, row: Any, *, event_id: str = "121350345"
) -> WorkoutDeliveryProposal:
    """The state the pre-335 swap left: another day's Red substitution under ``row``."""
    carried = adjust_ir_for_verdict(_plan(row), "Red")
    proposal = WorkoutDeliveryProposal(
        user_id=row.user_id,
        planned_workout_id=row.id,
        planned_workout_version=row.version,
        workout_date=row.workout_date,
        provider="intervals_icu",
        status=STATUS_PUSHED,
        proposed_at_utc=datetime(2026, 10, 8, 9, 40),
        pushed_at_utc=datetime(2026, 10, 8, 10, 7),
        structured_workout_ir=carried,
        intervals_payload=build_intervals_payload(carried),
        zwo_xml="",
        intervals_event_id=event_id,
    )
    session.add(proposal)
    await session.commit()
    return proposal


@pytest.mark.asyncio
async def test_the_daily_check_puts_the_plan_back_once(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    saturday = _sweet_spot(user_id, SAT)
    await _seed(db_conn, saturday)
    fake = _FakeIntervalsClient()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        await _carried_red_on(session, saturday)
        service = ExecutableCoachingService(session, intervals_client=fake)

        report = await service.check_live_rides(user, start_date=FRI, end_date=SUN, repair=False)
        assert [(c.workout_date, c.live_origin, c.repaired) for c in report] == [
            (SAT, "red_substitution", False)
        ]
        assert fake.updates == []

        found = await service.check_live_rides(user, start_date=FRI, end_date=SUN)
        assert [(c.workout_date, c.repaired, c.error) for c in found] == [(SAT, True, None)]
        assert found[0].live_title.startswith("Recovery substitution")
        assert [event for event, _ in fake.updates] == ["121350345"]
        live = await service.rail.latest_delivered_for_workout(user_id, saturday.id)
        assert live is not None and live.structured_workout_ir["origin"] == "as_planned"
        audits = (
            (
                await session.execute(
                    select(Analysis).where(
                        Analysis.user_id == user_id,
                        Analysis.analysis_type == AUDIT_TYPE_REPLACED,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert [a.context_packet["tag"] for a in audits] == [f"live-ride-check:{saturday.id}:v1"]

        assert await service.check_live_rides(user, start_date=FRI, end_date=SUN) == []
        assert len(fake.updates) == 1


@pytest.mark.asyncio
async def test_the_daily_check_finds_nothing_after_an_ftp_change(db_conn: AsyncConnection) -> None:
    """Production on 27 Oct: every event says 280 W, the profile says 267."""
    user_id = uuid.uuid4()
    rows = [_sweet_spot(user_id, THU), _easy_z2(user_id, SAT), _easy_z2(user_id, SUN, long=True)]
    await _seed(db_conn, *rows)
    fake = _FakeIntervalsClient()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=fake)
        await service.reconcile_deliveries(user, start_date=THU, end_date=SUN)
        session.add(
            KnowledgeBase(
                user_id=user_id,
                section="profile",
                version=1,
                is_active=True,
                content={"ftpWatts": 267},
            )
        )
        await session.commit()
        assert await service.rail._ftp_watts(user_id) == 267

        assert await service.check_live_rides(user, start_date=THU, end_date=SUN) == []
        assert len(fake.updates) == 0


@pytest.mark.asyncio
async def test_the_daily_check_leaves_this_days_changes_and_missing_events(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    thursday = _sweet_spot(user_id, THU)
    friday = _easy_z2(user_id, FRI)
    saturday = _easy_z2(user_id, SAT, long=True)
    await _seed(db_conn, thursday, friday, saturday)
    fake = _FakeIntervalsClient()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=fake)
        await service.reconcile_deliveries(user, start_date=THU, end_date=FRI)
        # Thursday: the morning's Red easing, approved. Friday: his own edit.
        morning = _morning(user_id, THU, "Red")
        session.add(morning)
        await session.commit()
        await service.regenerate_for_verdict(user, THU, analysis=morning)
        await service.approve_adjustment(user, planned_workout_id=thursday.id)
        await service.edit_today(user, planned_workout_id=friday.id, duration_scale_pct=80)
        # A later check-in reads Thursday again as Green: what he approved still stands.
        later = _morning(user_id, THU, "Green")
        later.generated_at_utc = datetime(2026, 10, 8, 14, 0)
        session.add(later)
        await session.commit()
        writes = len(fake.updates)

        # Saturday has no event at all: reconcile's to deliver, not the check's.
        assert await service.check_live_rides(user, start_date=THU, end_date=SAT) == []
        assert len(fake.updates) == writes
        assert len(fake.payloads) == 2

        reader = LiveRideReader(session, rail=service.rail)
        thu_ride = await reader.read(user_id, thursday)
        assert thu_ride is not None and thu_ride.state == LIVE_RIDE_CHANGED
        assert thu_ride.title.startswith("Recovery substitution")
        assert thu_ride.top_power_pct is not None and thu_ride.top_power_pct <= 60
        fri_ride = await reader.read(user_id, friday)
        assert fri_ride is not None and fri_ride.state == LIVE_RIDE_CHANGED


@pytest.mark.asyncio
async def test_restore_puts_the_plan_back_only_when_it_is_not_this_days_ride(
    db_conn: AsyncConnection,
) -> None:
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
        await _carried_red_on(session, saturday)

        with pytest.raises(HTTPException) as refused:
            await service.restore_plan_ride(user, planned_workout_id=sunday.id)
        assert refused.value.status_code == 409

        restored = await service.restore_plan_ride(user, planned_workout_id=saturday.id)
        assert restored.structured_workout_ir["origin"] == "as_planned"
        ride = await service.live_ride(user, saturday)
        assert ride is not None and ride.state == LIVE_RIDE_AS_PLANNED


@pytest.mark.asyncio
async def test_home_gets_the_live_ride_for_a_red_substitution(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    saturday = _sweet_spot(user_id, SAT)
    await _seed(db_conn, saturday)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        await _carried_red_on(session, saturday)
        states = await DailyLoopService(session)._deliveries(user_id, [saturday])

    ride = states[saturday.id].live_ride
    assert states[saturday.id].live_origin == "red_substitution"
    assert ride is not None
    assert ride.state == LIVE_RIDE_NOT_THIS_DAY
    assert ride.title == "Recovery substitution: Sweet Spot (1 × 30 min @ 89%)"
    assert ride.duration_min == 29
    assert ride.top_power_pct == 60


# -- the morning's offers and the week mix follow the live rows (UX333-02) --------------


def _red_thursday_with_swap(
    user_id: uuid.UUID, sweet_spot_id: uuid.UUID, easy_id: uuid.UUID
) -> Analysis:
    """8 Oct's stored morning: Red, the swap offer, both fixes listed, Sweet Spot short."""
    at_risk = {
        "bucket": "sweet_spot",
        "label": "Sweet Spot",
        "target": 1,
        "done": 0,
        "due": 1,
        "remainingPlanned": 0,
        "atRisk": True,
        "basis": "stored",
    }
    return Analysis(
        user_id=user_id,
        analysis_type="morning",
        subject_date=THU,
        generated_at_utc=datetime(2026, 10, 8, 8, 40),
        prompt_version="morning-analysis-test",
        verdict="Red",
        context_packet={
            "verdict": {
                "status": "Red",
                "swapSuggestion": {
                    "hardWorkoutId": str(sweet_spot_id),
                    "hardTitle": "Sweet Spot (1 × 30 min @ 89%)",
                    "moveToDate": SAT.isoformat(),
                    "moveToWeekday": "Saturday",
                    "bringForwardWorkoutId": str(easy_id),
                },
                "todayActions": [
                    {
                        "kind": "apply_swap",
                        "title": "Move Sweet Spot to Saturday",
                        "plannedWorkoutId": str(sweet_spot_id),
                        "targetDate": SAT.isoformat(),
                    },
                    {
                        "kind": "approve_ride",
                        "title": "Substitute recovery",
                        "plannedWorkoutId": str(sweet_spot_id),
                    },
                ],
                "weeklyMix": {
                    "weekStart": date(2026, 10, 5).isoformat(),
                    "subjectDate": THU.isoformat(),
                    "buckets": [at_risk],
                    "shortfall": {
                        "bucket": "sweet_spot",
                        "label": "Sweet Spot",
                        "repatched": True,
                        "moveToWeekday": "Saturday",
                        "moveToDate": SAT.isoformat(),
                        "message": "You'd be a Sweet Spot session short this week",
                    },
                },
            }
        },
        output_markdown="Red verdict",
        raw_response={},
    )


def _sweet_spot_bucket(mix: dict[str, Any] | None) -> dict[str, Any]:
    assert mix is not None
    return next(b for b in mix["buckets"] if b["bucket"] == "sweet_spot")


async def _offers(session: AsyncSession, user: Profile, morning: Analysis) -> tuple[Any, Any]:
    workouts = [row for row in [await _active(session, user.id, THU)] if row is not None]
    snapshot = SimpleNamespace(
        morning_analysis=morning,
        planned_workouts=workouts,
        deliveries=await DailyLoopService(session)._deliveries(user.id, workouts),
    )
    return await _with_live_offers(session, user, snapshot, _serialize_analysis(morning)), snapshot


@pytest.mark.asyncio
async def test_the_swap_offer_goes_once_either_fix_is_taken(db_conn: AsyncConnection) -> None:
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
        morning = _red_thursday_with_swap(user_id, thursday.id, saturday.id)
        session.add(morning)
        await session.commit()

        # Nothing taken yet: the stored morning, unchanged, live mix included.
        before, _ = await _offers(session, user, morning)
        assert before is not None
        assert before.swapSuggestion is not None
        assert [a["kind"] for a in before.todayActions] == ["apply_swap", "approve_ride"]
        assert _sweet_spot_bucket(before.weeklyMix)["atRisk"] is True
        assert before.weeklyMix["shortfall"]["bucket"] == "sweet_spot"

        # He approves the easier ride: the move offer goes (choose one).
        await service.regenerate_for_verdict(user, THU, analysis=morning)
        await service.approve_adjustment(user, planned_workout_id=thursday.id)
        approved, _ = await _offers(session, user, morning)
        assert approved is not None
        assert approved.swapSuggestion is None
        assert [a["kind"] for a in approved.todayActions] == ["approve_ride"]


@pytest.mark.asyncio
async def test_after_the_move_the_week_mix_and_the_alert_read_the_live_week(
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
        morning = _red_thursday_with_swap(user_id, thursday.id, saturday.id)
        previous = _morning(user_id, date(2026, 10, 7), "Green")
        previous.context_packet = {
            "verdict": {
                "status": "Green",
                "weeklyMix": {"buckets": [dict(_sweet_spot_bucket_stub(), atRisk=False)]},
            }
        }
        session.add_all([morning, previous])
        await session.commit()

        # Before the move the alert would fire, as it did at 10:45 on 8 Oct.
        before = await StateChangeCoachService(session)._candidates(user, as_of=THU)
        assert [c.snapshot.state_key for c in before] == ["weekly_mix:sweet_spot"]

        await service.swap_day(user, planned_workout_id=thursday.id, target_date=SAT)

        after, _ = await _offers(session, user, morning)
        assert after is not None
        assert after.swapSuggestion is None
        # The move offer goes; the approve offer's session has left today, so Home's own
        # check (its workout is no longer today's) drops it.
        assert [a["kind"] for a in after.todayActions] == ["approve_ride"]
        assert _sweet_spot_bucket(after.weeklyMix)["atRisk"] is False
        assert after.weeklyMix["shortfall"] is None
        assert await StateChangeCoachService(session)._candidates(user, as_of=THU) == []


@pytest.mark.asyncio
async def test_with_nothing_changed_the_live_mix_is_the_stored_mix(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    thursday = _sweet_spot(user_id, THU)
    saturday = _easy_z2(user_id, SAT)
    await _seed(db_conn, thursday, saturday)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        mixes = WeeklyMixService(session)
        for status in ("Green", "Amber", "Red"):
            stored = (
                await mixes.summarize_for_verdict(user, THU, verdict_status=status, swap=None)
            ).to_packet()
            morning = _morning(user_id, THU, status)
            morning.context_packet = {"verdict": {"status": status, "weeklyMix": stored}}
            assert await mixes.live_packet(user, morning) == stored, status


def _sweet_spot_bucket_stub() -> dict[str, Any]:
    return {
        "bucket": "sweet_spot",
        "label": "Sweet Spot",
        "target": 1,
        "done": 0,
        "due": 1,
        "remainingPlanned": 1,
        "atRisk": False,
        "basis": "stored",
    }


# -- the job ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_job_puts_the_ride_back_and_tells_craig(db_conn: AsyncConnection) -> None:
    from src.scheduler import run_live_ride_check

    user_id = uuid.uuid4()
    saturday = _sweet_spot(user_id, SAT)
    await _seed(db_conn, saturday)
    fake = _FakeIntervalsClient()
    logger = MagicMock()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        await _carried_red_on(session, saturday)
        user = await session.get(Profile, user_id)
        assert user is not None
        with (
            patch("src.scheduler.AsyncSessionLocal", return_value=_session_ctx(session)),
            patch("src.scheduler._active_profiles", return_value=[user]),
            patch("src.scheduler._profile_today", return_value=FRI),
            patch(
                "src.scheduler.ExecutableCoachingService",
                lambda s: ExecutableCoachingService(s, intervals_client=fake),
            ),
            patch("src.scheduler.log", logger),
        ):
            result = await run_live_ride_check()

    assert result.status == JobStatus.succeeded
    assert result.counters == {"profiles": 1, "found": 1, "repaired": 1, "failed": 0}
    alert = logger.error.call_args
    assert alert.args == ("zwift ride was not its day's ride",)
    assert alert.kwargs["admin_alert"] == "live_ride_mismatch"
    assert alert.kwargs["rides"][0]["date"] == SAT.isoformat()
    assert alert.kwargs["rides"][0]["repaired"] is True


@pytest.mark.asyncio
async def test_week_names_the_ride_on_zwift_from_today_on(db_conn: AsyncConnection) -> None:
    from src.routers.plan_actions import get_schedule

    user_id = uuid.uuid4()
    thursday = _sweet_spot(user_id, THU)
    saturday = _sweet_spot(user_id, SAT)
    sunday = _easy_z2(user_id, SUN, long=True)
    await _seed(db_conn, thursday, saturday, sunday)
    fake = _FakeIntervalsClient()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        await ExecutableCoachingService(session, intervals_client=fake).reconcile_deliveries(
            user, start_date=THU, end_date=SUN
        )
        await _carried_red_on(session, saturday, event_id="evt_sat")
        with patch("src.routers.plan_actions._local_today", return_value=FRI):
            envelope = await get_schedule(player=user, start_date=THU, days=4, db=session)

    rides = {
        workout.workoutDate: workout.zwiftRide
        for day in envelope.data.schedule
        for workout in day.workouts
    }
    assert rides[THU.isoformat()] is None  # before today: history, not shown
    sat = rides[SAT.isoformat()]
    assert sat is not None and sat.state == LIVE_RIDE_NOT_THIS_DAY
    assert (sat.durationMin, sat.topPowerPct) == (29, 60)
    sun = rides[SUN.isoformat()]
    assert sun is not None and sun.state == LIVE_RIDE_AS_PLANNED


@pytest.mark.asyncio
async def test_a_second_ride_never_takes_the_first_rides_event(db_conn: AsyncConnection) -> None:
    """Two indoor rides on one day, only the first on Zwift: the check leaves its event."""
    user_id = uuid.uuid4()
    first = _sweet_spot(user_id, SAT)
    second = _easy_z2(user_id, SAT)
    await _seed(db_conn, first)
    fake = _FakeIntervalsClient()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=fake)
        await service.reconcile_deliveries(user, start_date=SAT, end_date=SAT)
        second.version = 2
        session.add(second)
        await session.commit()

        reader = LiveRideReader(session, rail=service.rail)
        assert await reader.live_event(user_id, second) is None
        assert await reader.read(user_id, second) is None
        assert await service.check_live_rides(user, start_date=SAT, end_date=SAT) == []
        assert fake.updates == []
