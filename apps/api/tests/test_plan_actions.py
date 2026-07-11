from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import (
    Analysis,
    ManualEntry,
    PlanBlock,
    PlannedWorkout,
    WorkoutDeliveryProposal,
)
from src.models.profile import Profile, UserRole
from src.services.holiday_pause import HolidayPauseService
from src.services.plan_actions import (
    TOTAL_WEEKS,
    PlanActionService,
    quick_add_options,
    week_character_for_day,
    workout_for_selection,
)
from src.services.structured_workout_builder import (
    FreeformBikeWorkoutSpec,
    WorkoutSegment,
    build_freeform_bike_workout,
)
from src.services.workout_categories import day_state_for_workout_types
from src.services.workout_delivery import (
    STATUS_PUSHED,
    IntervalsCreateResult,
    expand_structured_steps,
    validate_deliverable_bike_workout,
)


def _ramp(duration_min: int, start: int, end: int) -> WorkoutSegment:
    return WorkoutSegment(
        kind="ramp", duration_min=duration_min, start_ftp_pct=start, end_ftp_pct=end
    )


def _steady(duration_min: int, pct: int) -> WorkoutSegment:
    return WorkoutSegment(kind="steady", duration_min=duration_min, ftp_pct=pct)


def _interval(repeats: int, work: int, work_pct: int, rec: int, rec_pct: int) -> WorkoutSegment:
    return WorkoutSegment(
        kind="interval",
        repeats=repeats,
        work_min=work,
        work_ftp_pct=work_pct,
        recover_min=rec,
        recover_ftp_pct=rec_pct,
    )


def _spec(*segments: WorkoutSegment, delivery: str = "indoor") -> FreeformBikeWorkoutSpec:
    return FreeformBikeWorkoutSpec(delivery=delivery, segments=tuple(segments))


class _FakeIntervalsClient:
    def __init__(self) -> None:
        self.payloads: list[dict] = []
        self.updates: list[tuple[str, dict]] = []
        self.deletes: list[str] = []
        self._counter = 0

    async def create_workout_event(self, payload: dict) -> IntervalsCreateResult:
        self.payloads.append(payload)
        self._counter += 1
        event_id = f"evt_{self._counter}"
        return IntervalsCreateResult(event_id=event_id, raw_response={"id": event_id})

    async def update_workout_event(self, event_id: str, payload: dict) -> IntervalsCreateResult:
        self.updates.append((event_id, payload))
        return IntervalsCreateResult(event_id=event_id, raw_response={"id": event_id})

    async def delete_workout_event(self, event_id: str) -> None:
        self.deletes.append(event_id)


async def _seed_user(session: AsyncSession, user_id: uuid.UUID) -> Profile:
    user = Profile(
        id=user_id,
        display_name="Plan Action Test",
        pin_hash="x" * 60,
        role=UserRole.admin,
        timezone="Europe/London",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def _seed_workout(
    session: AsyncSession,
    user_id: uuid.UUID,
    workout_date: date,
    *,
    workout_id: uuid.UUID | None = None,
    version: int = 1,
    workout_type: str = "strength_maintenance",
    structured: dict | None = None,
) -> PlannedWorkout:
    workout = PlannedWorkout(
        id=workout_id or uuid.uuid4(),
        user_id=user_id,
        workout_date=workout_date,
        version=version,
        title="Strength maintenance" if workout_type.startswith("strength") else "Endurance ride",
        workout_type=workout_type,
        status="planned",
        is_active=True,
        planned_duration_min=20 if workout_type.startswith("strength") else 45,
        intensity_target="maintenance" if workout_type.startswith("strength") else "Zone 2",
        structured_workout=structured
        or (
            {"format": "strength", "focus": "maintenance"}
            if workout_type.startswith("strength")
            else {
                "format": "bike",
                "steps": [
                    {"label": "Warm-up", "minutes": 5, "target": "easy"},
                    {"label": "Endurance", "minutes": 35, "target": "zone 2"},
                    {"label": "Cool-down", "minutes": 5, "target": "easy"},
                ],
            }
        ),
        source="test",
    )
    session.add(workout)
    await session.flush()
    return workout


def _block(
    session: AsyncSession,
    user_id: uuid.UUID,
    seq: int,
    block_type: str,
    start: date,
) -> PlanBlock:
    block = PlanBlock(
        id=uuid.uuid4(),
        user_id=user_id,
        name=f"Week {seq:02d} {block_type.title()}",
        version=1,
        sequence_index=seq,
        block_type=block_type,
        start_date=start,
        end_date=start + timedelta(days=6),
        goals_json={},
        raw_plan={},
    )
    session.add(block)
    return block


def test_day_state_labels_mixed_and_rest() -> None:
    rest = day_state_for_workout_types([])
    assert rest.label == "Rest"
    assert rest.is_rest is True

    mixed = day_state_for_workout_types(["bike_endurance", "strength_maintenance", "mobility"])
    assert mixed.categories == ["cycle", "weights", "flexibility"]
    assert mixed.label == "Cycle + Weights + Flexibility"


@pytest.mark.asyncio
async def test_schedule_groups_live_days_with_explicit_rest(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    monday = date(2026, 8, 10)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await _seed_user(session, user_id)
        await _seed_workout(session, user_id, monday, workout_type="bike_endurance")
        await _seed_workout(session, user_id, monday, version=2, workout_type="mobility")
        await session.commit()

        schedule = await PlanActionService(session).schedule(user, start_date=monday, days=3)

    assert [day.date for day in schedule.days] == [monday, date(2026, 8, 11), date(2026, 8, 12)]
    assert schedule.days[0].day_state.label == "Cycle + Flexibility"
    assert len(schedule.days[0].workouts) == 2
    assert schedule.days[1].day_state.label == "Rest"
    assert schedule.days[1].workouts == []


@pytest.mark.asyncio
async def test_add_workout_appends_to_occupied_day_and_bike_reconciles(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    day = date(2026, 8, 13)
    fake = _FakeIntervalsClient()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await _seed_user(session, user_id)
        await _seed_workout(session, user_id, day, workout_type="strength_maintenance")
        await session.commit()

        added = await PlanActionService(session, intervals_client=fake).add_workout(
            user, workout_date=day, category="cycle"
        )

        workouts = (
            (
                await session.execute(
                    select(PlannedWorkout).where(
                        PlannedWorkout.user_id == user_id,
                        PlannedWorkout.workout_date == day,
                        PlannedWorkout.is_active.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        proposals = (
            (
                await session.execute(
                    select(WorkoutDeliveryProposal).where(
                        WorkoutDeliveryProposal.planned_workout_id == added.id
                    )
                )
            )
            .scalars()
            .all()
        )

    assert len(workouts) == 2
    assert added.version == 2
    assert fake.payloads[0]["name"] == "Endurance ride"
    assert proposals[0].status == STATUS_PUSHED


def test_quick_add_options_lists_selectable_subtypes_per_category() -> None:
    cycle_subtypes = {option.subtype for option in quick_add_options("cycle")}
    weights_subtypes = {option.subtype for option in quick_add_options("weights")}
    flexibility_subtypes = {option.subtype for option in quick_add_options("flexibility")}

    assert cycle_subtypes == {"endurance", "sweet_spot", "recovery", "tempo", "vo2_efforts"}
    assert weights_subtypes == {"maintenance", "recovery"}
    assert flexibility_subtypes == {"mobility"}

    with pytest.raises(HTTPException):
        quick_add_options("rest")


def test_tempo_quick_add_builds_ramp_warmup_and_cooldown() -> None:
    """Batch 75: tempo/threshold is authored with real ramp warm-up/cool-down
    (Batch 67 step grammar) rather than a flat 'easy' block."""
    result = workout_for_selection("cycle", subtype="tempo", duration_min=40)

    assert result["workout_type"] == "bike_tempo"
    assert result["planned_duration_min"] == 40
    steps = result["structured_workout"]["steps"]
    assert steps[0]["ramp"] == [55, 80]
    assert steps[-1]["ramp"] == [65, 40]
    assert steps[1]["target"] == "84%"
    assert sum(step["minutes"] for step in steps) == 40

    expanded = validate_deliverable_bike_workout(
        result["structured_workout"], result["intensity_target"], context="test"
    )
    assert any(step["kind"] == "ramp" for step in expanded)


def test_vo2_efforts_quick_add_builds_interval_pattern_at_explicit_pct() -> None:
    """Batch 75: VO2 'with efforts' authors real work/recovery interval reps
    (not a flat block), sized to the nearest whole rep count for the chosen
    duration, and delivers a real IR through the Batch 67 grammar."""
    result = workout_for_selection("cycle", subtype="vo2_efforts", duration_min=38)

    assert result["workout_type"] == "bike_vo2"
    assert result["planned_duration_min"] == 38
    main_step = result["structured_workout"]["steps"][1]
    assert main_step["pattern"] == "5 x 2min / 2min @60%"
    assert main_step["target"] == "118%"

    expanded = expand_structured_steps(result["structured_workout"], result["intensity_target"])
    work_steps = [step for step in expanded if step["powerStartPct"] == 118]
    recovery_steps = [step for step in expanded if step["powerStartPct"] == 60]
    assert len(work_steps) == 5
    assert len(recovery_steps) == 5


def test_vo2_efforts_quick_add_reports_true_traced_duration_off_boundary() -> None:
    """A requested duration that doesn't land on a whole rep boundary rounds to
    the nearest valid rep count, and the returned duration reflects what was
    actually built — not the raw request — so it always traces the steps."""
    result = workout_for_selection("cycle", subtype="vo2_efforts", duration_min=32)

    steps = result["structured_workout"]["steps"]
    total_ramp_min = steps[0]["minutes"] + steps[-1]["minutes"]
    match = re.match(r"(\d+) x", steps[1]["pattern"])
    assert match is not None
    reps = int(match.group(1))
    assert 3 <= reps <= 8
    assert result["planned_duration_min"] == total_ramp_min + reps * 4


def test_quick_add_rejects_vo2_efforts_duration_outside_bounds() -> None:
    with pytest.raises(HTTPException):
        workout_for_selection("cycle", subtype="vo2_efforts", duration_min=100)


def test_freeform_builder_maps_ordered_segments_to_steps() -> None:
    built, warnings = build_freeform_bike_workout(
        _spec(
            _ramp(10, 45, 75),
            _steady(8, 55),
            _interval(4, 3, 112, 2, 55),
            _ramp(6, 75, 45),
        ),
        soft_gates=True,
    )

    assert warnings == []
    assert built.workout_type == "bike_vo2"
    assert built.planned_duration_min == 44  # 10 + 8 + 4*(3+2) + 6
    assert built.structured_workout["delivery"] == "indoor"
    assert built.structured_workout["steps"] == [
        {"label": "Warm-up ramp", "minutes": 10, "ramp": [45, 75]},
        {"label": "Steady", "minutes": 8, "target": "55%"},
        {"label": "Intervals", "target": "112%", "pattern": "4 x 3min / 2min @55%"},
        {"label": "Cool-down ramp", "minutes": 6, "ramp": [75, 45]},
    ]
    expanded = expand_structured_steps(built.structured_workout, built.intensity_target)
    assert len([step for step in expanded if step["powerEndPct"] == 112]) == 4


def test_freeform_builder_preserves_arbitrary_segment_order() -> None:
    built, _ = build_freeform_bike_workout(
        _spec(
            _ramp(5, 45, 75),
            _interval(2, 1, 120, 1, 50),
            _steady(8, 80),
            _interval(3, 2, 105, 2, 60),
            _ramp(5, 75, 45),
        ),
        soft_gates=True,
    )
    assert [step["label"] for step in built.structured_workout["steps"]] == [
        "Warm-up ramp",
        "Intervals",
        "Steady",
        "Intervals",
        "Cool-down ramp",
    ]


def test_freeform_soft_gates_warn_not_block_on_manual_path() -> None:
    # A short 160% sprint with no cool-down ramp: both gates warn, nothing is rejected.
    built, warnings = build_freeform_bike_workout(
        _spec(_ramp(10, 45, 75), _steady(2, 160)), soft_gates=True
    )
    codes = {warning.code for warning in warnings}
    assert codes == {"power_out_of_band", "missing_ramp"}
    assert built.planned_duration_min == 12
    assert built.workout_type == "bike_vo2"


def test_freeform_hard_mode_blocks_out_of_band_and_missing_ramp() -> None:
    # The coach/automated path (soft_gates=False, the default) keeps both gates hard.
    with pytest.raises(HTTPException):
        build_freeform_bike_workout(
            _spec(_ramp(10, 45, 75), _steady(2, 160), _ramp(5, 75, 45)), soft_gates=False
        )
    with pytest.raises(HTTPException):
        build_freeform_bike_workout(_spec(_steady(30, 65)), soft_gates=False)


def test_freeform_absolute_floor_rejects_even_under_soft_gates() -> None:
    # Power beyond the deliverable ceiling is rejected even on the manual path.
    with pytest.raises(HTTPException):
        build_freeform_bike_workout(
            _spec(_ramp(10, 45, 75), _steady(10, 400), _ramp(5, 75, 45)), soft_gates=True
        )
    # An absurd total duration is rejected even on the manual path.
    with pytest.raises(HTTPException):
        build_freeform_bike_workout(
            _spec(_ramp(10, 45, 75), _steady(300, 65), _steady(300, 65), _ramp(5, 75, 45)),
            soft_gates=True,
        )


def test_import_gate_stays_hard_on_rampless_bike_workout() -> None:
    # The coach/automated import path keeps its own hard ramp gate, independent of the
    # builder flag — a rampless plan still fails loudly at import.
    with pytest.raises(ValueError):
        validate_deliverable_bike_workout(
            {"format": "bike", "steps": [{"label": "Block", "minutes": 30, "target": "65%"}]},
            None,
        )


@pytest.mark.asyncio
async def test_add_workout_honours_chosen_subtype_and_duration(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    day = date(2026, 8, 24)
    fake = _FakeIntervalsClient()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await _seed_user(session, user_id)
        await session.commit()

        added = await PlanActionService(session, intervals_client=fake).add_workout(
            user, workout_date=day, category="cycle", subtype="sweet_spot", duration_min=50
        )

    assert added.warnings == []
    assert added.workout.workout_type == "bike_sweet_spot"
    assert added.workout.title == "Sweet Spot ride"
    assert added.workout.planned_duration_min == 50
    steps = added.workout.structured_workout["steps"]
    assert sum(step["minutes"] for step in steps) == 50


@pytest.mark.asyncio
async def test_add_custom_indoor_workout_delivers_and_outdoor_does_not(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    indoor_day = date(2026, 8, 26)
    outdoor_day = date(2026, 8, 27)
    fake = _FakeIntervalsClient()
    segments = (_ramp(10, 45, 75), _steady(40, 84), _ramp(5, 75, 45))
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await _seed_user(session, user_id)
        await session.commit()
        service = PlanActionService(session, intervals_client=fake)

        indoor = await service.add_workout(
            user,
            workout_date=indoor_day,
            category="cycle",
            custom_bike=_spec(*segments, delivery="indoor"),
        )
        outdoor = await service.add_workout(
            user,
            workout_date=outdoor_day,
            category="cycle",
            custom_bike=_spec(*segments, delivery="outdoor"),
        )

    assert indoor.workout.structured_workout["delivery"] == "indoor"
    assert outdoor.workout.structured_workout["delivery"] == "outdoor"
    assert len(fake.payloads) == 1
    assert fake.payloads[0]["start_date_local"] == "2026-08-26T00:00:00"


@pytest.mark.asyncio
async def test_add_workout_rejects_duration_outside_subtype_bounds(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    day = date(2026, 8, 25)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await _seed_user(session, user_id)
        await session.commit()

        with pytest.raises(HTTPException):
            await PlanActionService(session).add_workout(
                user, workout_date=day, category="cycle", subtype="recovery", duration_min=120
            )


@pytest.mark.asyncio
async def test_structured_edit_versions_row_and_resyncs_zwift(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    day = date(2026, 8, 28)
    workout_id = uuid.uuid4()
    fake = _FakeIntervalsClient()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await _seed_user(session, user_id)
        original = await _seed_workout(
            session, user_id, day, workout_id=workout_id, workout_type="bike_endurance"
        )
        await session.commit()
        service = PlanActionService(session, intervals_client=fake)
        await service.executable.reconcile_deliveries(user, start_date=day, end_date=day)

        edited = await service.edit_structured_workout(
            user,
            planned_workout_id=original.id,
            custom_bike=_spec(
                _ramp(8, 45, 75),
                _interval(5, 2, 118, 2, 55),
                _ramp(6, 75, 45),
            ),
        )
        rows = (
            (
                await session.execute(
                    select(PlannedWorkout)
                    .where(PlannedWorkout.user_id == user_id, PlannedWorkout.workout_date == day)
                    .order_by(PlannedWorkout.version.asc())
                )
            )
            .scalars()
            .all()
        )
        proposal = await session.scalar(
            select(WorkoutDeliveryProposal).where(
                WorkoutDeliveryProposal.planned_workout_id == edited.workout.id
            )
        )

    assert [(row.id, row.is_active) for row in rows] == [
        (original.id, False),
        (edited.workout.id, True),
    ]
    assert edited.workout.version == 2
    assert edited.workout.workout_type == "bike_vo2"
    assert fake.updates
    assert proposal is not None
    assert proposal.planned_workout_version == 2


def _seed_morning_verdict(user_id: uuid.UUID, day: date, verdict: str) -> Analysis:
    return Analysis(
        user_id=user_id,
        analysis_type="morning",
        subject_date=day,
        generated_at_utc=datetime(day.year, day.month, day.day, 6, 30),
        prompt_version="test",
        verdict=verdict,
        context_packet={},
        output_markdown="",
        raw_response={},
    )


@pytest.mark.asyncio
async def test_add_custom_vo2_on_red_day_warns_but_still_delivers(db_conn: AsyncConnection) -> None:
    """Batch 88 / Decision #161: a VO2 ride Mark explicitly authors for a Red-readiness
    day is delivered with a warning rather than blocked — the scoped reversal. The
    coach-adjustment delivery gates keep Red-never-VO2 hard (tested in executable)."""
    user_id = uuid.uuid4()
    day = date(2026, 9, 2)
    fake = _FakeIntervalsClient()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await _seed_user(session, user_id)
        session.add(_seed_morning_verdict(user_id, day, "Red"))
        await session.commit()

        result = await PlanActionService(session, intervals_client=fake).add_workout(
            user,
            workout_date=day,
            category="cycle",
            custom_bike=_spec(_ramp(10, 45, 75), _interval(4, 4, 118, 4, 55), _ramp(5, 75, 45)),
        )

    assert any(warning.code == "red_vo2" for warning in result.warnings)
    assert result.workout.workout_type == "bike_vo2"
    assert len(fake.payloads) == 1  # delivered despite Red — warn-not-block on the manual path


@pytest.mark.asyncio
async def test_add_custom_endurance_on_red_day_has_no_vo2_warning(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    day = date(2026, 9, 3)
    fake = _FakeIntervalsClient()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await _seed_user(session, user_id)
        session.add(_seed_morning_verdict(user_id, day, "Red"))
        await session.commit()

        result = await PlanActionService(session, intervals_client=fake).add_workout(
            user,
            workout_date=day,
            category="cycle",
            custom_bike=_spec(_ramp(10, 45, 75), _steady(30, 65), _ramp(5, 75, 45)),
        )

    assert result.warnings == []


@pytest.mark.asyncio
async def test_move_ride_onto_flexibility_day_is_category_scoped(db_conn: AsyncConnection) -> None:
    """Batch 65: moving a ride onto a day that only holds a flexibility session is a
    move, not a cross-category swap — the ride joins that day and the flexibility
    stays put, so nothing is dragged back onto the vacated day."""
    user_id = uuid.uuid4()
    monday, wednesday = date(2026, 8, 17), date(2026, 8, 19)
    workout_id = uuid.uuid4()
    fake = _FakeIntervalsClient()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await _seed_user(session, user_id)
        await _seed_workout(
            session, user_id, monday, workout_id=workout_id, workout_type="bike_endurance"
        )
        await session.commit()
        service = PlanActionService(session, intervals_client=fake)
        await service.executable.reconcile_deliveries(user, start_date=monday, end_date=monday)
        await service.add_workout(user, workout_date=wednesday, category="flexibility")

        moved = await service.swap_workout_into_date(
            user, planned_workout_id=workout_id, target_date=wednesday
        )

        async def _active_on(day: date) -> list[PlannedWorkout]:
            return list(
                (
                    await session.execute(
                        select(PlannedWorkout)
                        .where(
                            PlannedWorkout.user_id == user_id,
                            PlannedWorkout.workout_date == day,
                            PlannedWorkout.is_active.is_(True),
                        )
                        .order_by(PlannedWorkout.version)
                    )
                )
                .scalars()
                .all()
            )

        monday_active = await _active_on(monday)
        wednesday_active = await _active_on(wednesday)

    assert moved.workout_date == wednesday
    # The flexibility is NOT dragged back — Monday is now empty.
    assert monday_active == []
    # Wednesday carries both its flexibility and the moved ride.
    assert sorted(w.workout_type for w in wednesday_active) == ["bike_endurance", "mobility"]
    assert fake.updates  # the ride's Zwift event moved


@pytest.mark.asyncio
async def test_skip_day_skips_every_active_workout(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    day = date(2026, 8, 20)
    fake = _FakeIntervalsClient()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await _seed_user(session, user_id)
        await _seed_workout(session, user_id, day, workout_type="bike_endurance")
        await _seed_workout(session, user_id, day, version=2, workout_type="mobility")
        await session.commit()

        skipped = await PlanActionService(session, intervals_client=fake).skip_day(
            user, workout_date=day
        )

        rows = (
            (
                await session.execute(
                    select(PlannedWorkout).where(
                        PlannedWorkout.user_id == user_id,
                        PlannedWorkout.workout_date == day,
                    )
                )
            )
            .scalars()
            .all()
        )

    assert len(skipped) == 2
    assert {row.status for row in rows} == {"skipped"}


@pytest.mark.asyncio
async def test_skip_day_leaves_completed_and_logged_workouts_intact(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    day = date(2026, 8, 20)
    fake = _FakeIntervalsClient()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await _seed_user(session, user_id)
        done = await _seed_workout(session, user_id, day, workout_type="bike_endurance")
        done.status = "completed"
        outstanding = await _seed_workout(session, user_id, day, version=2, workout_type="mobility")
        logged = await _seed_workout(
            session,
            user_id,
            day,
            version=3,
            workout_type="strength_maintenance",
        )
        session.add(
            ManualEntry(
                user_id=user_id,
                planned_workout_id=logged.id,
                entry_date=day,
                entry_at_utc=datetime(2026, 8, 20, 8, 0, 0),
                adherence_status="modified",
            )
        )
        await session.commit()

        skipped = await PlanActionService(session, intervals_client=fake).skip_day(
            user, workout_date=day
        )

        rows = (
            (
                await session.execute(
                    select(PlannedWorkout)
                    .where(
                        PlannedWorkout.user_id == user_id,
                        PlannedWorkout.workout_date == day,
                    )
                    .order_by(PlannedWorkout.version.asc())
                )
            )
            .scalars()
            .all()
        )

    assert [workout.id for workout in skipped] == [outstanding.id]
    assert [(row.id, row.status) for row in rows] == [
        (done.id, "completed"),
        (outstanding.id, "skipped"),
        (logged.id, "planned"),
    ]


@pytest.mark.asyncio
async def test_schedule_excludes_skipped_workouts_for_week_parity(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    day = date(2026, 8, 21)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await _seed_user(session, user_id)
        planned = await _seed_workout(session, user_id, day, workout_type="bike_endurance")
        skipped = await _seed_workout(session, user_id, day, version=2, workout_type="mobility")
        skipped.status = "skipped"
        await session.commit()

        schedule = await PlanActionService(session).schedule(user, start_date=day, days=1)

    assert [workout.id for workout in schedule.days[0].workouts] == [planned.id]


# ----------------------------------------------------------
# Batch 81 — calendar-aware week view: block character + holiday overlay
# ----------------------------------------------------------


def test_week_character_labels_each_block_type() -> None:
    build = PlanBlock(
        user_id=uuid.uuid4(),
        name="Week 04 Build",
        version=1,
        sequence_index=4,
        block_type="build",
        start_date=date(2026, 8, 3),
        end_date=date(2026, 8, 9),
        goals_json={},
        raw_plan={},
    )
    character = week_character_for_day(build, is_holiday=False)
    assert character is not None
    assert character.label == f"Build 4/{TOTAL_WEEKS}"
    assert character.sequence_index == 4
    assert character.block_type == "build"
    assert character.is_holiday is False

    for block_type, label in [
        ("recovery", "Reset"),
        ("taper", "Taper"),
        ("consolidation", "Consolidation"),
    ]:
        build.block_type = block_type
        result = week_character_for_day(build, is_holiday=False)
        assert result is not None
        assert result.label == label
        assert result.is_holiday is False


def test_week_character_holiday_overrides_the_block() -> None:
    block = PlanBlock(
        user_id=uuid.uuid4(),
        name="Week 05 Build",
        version=1,
        sequence_index=5,
        block_type="build",
        start_date=date(2026, 8, 10),
        end_date=date(2026, 8, 16),
        goals_json={},
        raw_plan={},
    )
    character = week_character_for_day(block, is_holiday=True)
    assert character is not None
    assert character.label == "Holiday"
    assert character.is_holiday is True
    # The overridden block's identity is still surfaced (useful for the client).
    assert character.sequence_index == 5
    assert character.block_type == "build"


def test_week_character_is_none_without_a_block_or_holiday() -> None:
    assert week_character_for_day(None, is_holiday=False) is None


@pytest.mark.asyncio
async def test_schedule_attaches_week_character_from_plan_block(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    monday = date(2026, 8, 24)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await _seed_user(session, user_id)
        _block(session, user_id, 6, "recovery", monday)
        await _seed_workout(session, user_id, monday, workout_type="bike_endurance")
        await session.commit()

        schedule = await PlanActionService(session).schedule(user, start_date=monday, days=3)

    assert schedule.days[0].week_character is not None
    assert schedule.days[0].week_character.label == "Reset"
    assert schedule.days[0].week_character.is_holiday is False


@pytest.mark.asyncio
async def test_schedule_surfaces_active_holiday_window(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    monday = date(2026, 9, 7)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await _seed_user(session, user_id)
        _block(session, user_id, 7, "build", monday)
        await session.commit()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        await HolidayPauseService(session).pause(user, monday, monday + timedelta(days=2))

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        schedule = await PlanActionService(session).schedule(user, start_date=monday, days=5)

    # Days inside the holiday window read "Holiday" even though the underlying
    # block is a build week; days after resume revert to the block's own character.
    assert schedule.days[0].week_character is not None
    assert schedule.days[0].week_character.label == "Holiday"
    assert schedule.days[2].week_character is not None
    assert schedule.days[2].week_character.label == "Holiday"
    assert schedule.days[4].week_character is not None
    assert schedule.days[4].week_character.label == "Build 7/13"


# ----------------------------------------------------------
# Batch 82 — manual light reset week: Z2 rides + strength kept
# ----------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_reset_week_versions_bikes_to_z2_keeps_strength_and_resyncs(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    monday = date(2026, 9, 14)
    tuesday = monday + timedelta(days=1)
    wednesday = monday + timedelta(days=2)
    fake = _FakeIntervalsClient()
    vo2_structured = {
        "format": "bike",
        "delivery": "indoor",
        "steps": [
            {"label": "Warm-up ramp", "minutes": 10, "ramp": [45, 75]},
            {"label": "Main intervals", "target": "118%", "pattern": "4 x 2min / 2min @55%"},
            {"label": "Cool-down ramp", "minutes": 5, "ramp": [75, 45]},
        ],
    }
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await _seed_user(session, user_id)
        _block(session, user_id, 8, "build", monday)
        ride = await _seed_workout(
            session,
            user_id,
            tuesday,
            workout_type="bike_vo2",
            structured=vo2_structured,
        )
        strength = await _seed_workout(
            session, user_id, wednesday, workout_type="strength_maintenance"
        )
        await session.commit()
        service = PlanActionService(session, intervals_client=fake)
        await service.executable.reconcile_deliveries(user, start_date=tuesday, end_date=tuesday)

        active = await service.mark_reset_week(user, week_date=monday)

        rows = (
            (
                await session.execute(
                    select(PlannedWorkout)
                    .where(PlannedWorkout.user_id == user_id)
                    .order_by(PlannedWorkout.workout_date.asc(), PlannedWorkout.version.asc())
                )
            )
            .scalars()
            .all()
        )
        block = await session.scalar(select(PlanBlock).where(PlanBlock.user_id == user_id))
        schedule = await service.schedule(user, start_date=monday, days=1)

    reset_ride = next(workout for workout in active if workout.source == "reset_week")
    assert [(row.id, row.is_active) for row in rows if row.workout_date == tuesday] == [
        (ride.id, False),
        (reset_ride.id, True),
    ]
    assert strength.id in {workout.id for workout in active}
    assert reset_ride.title == "Reset Z2: Endurance ride"
    assert reset_ride.workout_type == "bike_endurance"
    assert reset_ride.intensity_target == "Z2 reset ~65% FTP"
    expanded = expand_structured_steps(reset_ride.structured_workout, reset_ride.intensity_target)
    assert {step["powerStartPct"] for step in expanded} == {65}
    assert {step["powerEndPct"] for step in expanded} == {65}
    assert reset_ride.structured_workout["resetWeek"]["originalWorkoutId"] == str(ride.id)
    assert block is not None
    assert block.goals_json["manualResetWeek"]["active"] is True
    assert schedule.days[0].week_character is not None
    assert schedule.days[0].week_character.label == "Light reset"
    assert schedule.days[0].week_character.is_reset is True
    assert fake.updates


@pytest.mark.asyncio
async def test_unset_reset_week_restores_original_versions_and_resyncs(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    monday = date(2026, 9, 21)
    tuesday = monday + timedelta(days=1)
    fake = _FakeIntervalsClient()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await _seed_user(session, user_id)
        _block(session, user_id, 9, "build", monday)
        original = await _seed_workout(session, user_id, tuesday, workout_type="bike_sweet_spot")
        await session.commit()
        service = PlanActionService(session, intervals_client=fake)
        await service.executable.reconcile_deliveries(user, start_date=tuesday, end_date=tuesday)
        await service.mark_reset_week(user, week_date=monday)

        restored = await service.unset_reset_week(user, week_date=monday)

        rows = (
            (
                await session.execute(
                    select(PlannedWorkout)
                    .where(PlannedWorkout.user_id == user_id)
                    .order_by(PlannedWorkout.version.asc())
                )
            )
            .scalars()
            .all()
        )
        block = await session.scalar(select(PlanBlock).where(PlanBlock.user_id == user_id))

    assert [workout.id for workout in restored] == [original.id]
    assert [(row.id, row.is_active) for row in rows] == [(original.id, True), (rows[1].id, False)]
    assert rows[1].source == "reset_week"
    assert block is not None
    assert block.goals_json["manualResetWeek"]["active"] is False
    assert len(fake.updates) >= 2


@pytest.mark.asyncio
async def test_record_actual_captures_unplanned_reality(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    day = date(2026, 8, 22)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await _seed_user(session, user_id)
        await session.commit()

        entry = await PlanActionService(session).record_actual(
            user,
            workout_date=day,
            label="Walked instead",
            notes="Easy 40 minutes.",
        )

        stored = await session.get(ManualEntry, entry.id)

    assert stored is not None
    assert stored.planned_workout_id is None
    assert stored.adherence_status == "modified"
    assert stored.actual_workout_json == {"label": "Walked instead", "source": "did_something_else"}
