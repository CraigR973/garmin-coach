from __future__ import annotations

import uuid
from datetime import date, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import Activity, Analysis, PlannedWorkout
from src.models.profile import Profile, UserRole
from src.services.training_week import TrainingWeekService, build_training_week_packet

MON = date(2026, 7, 20)
TUE = date(2026, 7, 21)
WED = date(2026, 7, 22)
SAT = date(2026, 7, 25)


def _workout(
    *,
    workout_date: date,
    title: str,
    workout_type: str,
    status: str = "planned",
    active: bool = True,
    version: int = 1,
) -> PlannedWorkout:
    return PlannedWorkout(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        workout_date=workout_date,
        version=version,
        title=title,
        workout_type=workout_type,
        status=status,
        is_active=active,
        planned_duration_min=60,
        intensity_target=None,
        structured_workout={},
        source="test",
    )


def _activity(
    *,
    start_utc: datetime,
    title: str,
    activity_type: str = "cycling",
    training_load: float = 42.0,
) -> Activity:
    return Activity(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        garmin_activity_id=int(start_utc.strftime("%m%d%H%M%S")),
        activity_name=title,
        activity_type=activity_type,
        start_utc=start_utc,
        duration_sec=3600,
        training_load=training_load,
        avg_power_watts=170,
        normalized_power_watts=178,
        aerobic_training_effect=2.4,
        anaerobic_training_effect=0.1,
        raw_summary={},
    )


def _audit(
    *,
    analysis_type: str,
    subject_date: date,
    summary: str,
    linked_workout: PlannedWorkout,
    tag: str,
) -> Analysis:
    return Analysis(
        id=uuid.uuid4(),
        user_id=linked_workout.user_id,
        activity_id=None,
        analysis_type=analysis_type,
        subject_date=subject_date,
        generated_at_utc=datetime(2026, 7, 21, 7, 0),
        prompt_version="executable-coaching:v1",
        model_name=None,
        verdict=None,
        context_packet={
            "tag": tag,
            "plannedWorkoutId": str(linked_workout.id),
            "plannedWorkoutVersion": linked_workout.version,
            "status": analysis_type.removeprefix("workout_"),
        },
        output_markdown=summary,
        raw_response={},
    )


def _day(packet: dict[str, object], day: date) -> dict[str, object]:
    days = packet["days"]
    assert isinstance(days, list)
    return next(row for row in days if row["date"] == day.isoformat())


def test_swapped_vo2_is_changed_not_executed_on_its_old_day() -> None:
    easy = _workout(
        workout_date=TUE,
        title="Easy Z2",
        workout_type="bike_endurance",
        status="completed",
        version=2,
    )
    vo2 = _workout(
        workout_date=SAT,
        title="VO2 Max",
        workout_type="bike_vo2",
        version=2,
    )
    easy.user_id = vo2.user_id
    actual = _activity(start_utc=datetime(2026, 7, 21, 17, 0), title="Easy Z2 ride")
    actual.user_id = vo2.user_id
    moved = _audit(
        analysis_type="workout_moved",
        subject_date=TUE,
        summary="Swapped 2026-07-21 and 2026-07-25.",
        linked_workout=vo2,
        tag=f"swap:{uuid.uuid4()}:{SAT.isoformat()}",
    )

    packet = build_training_week_packet(
        start_date=MON,
        end_date=SAT,
        timezone_name="Europe/London",
        planned_workouts=[easy, vo2],
        action_audits=[moved],
        activities=[actual],
        workouts_by_id={easy.id: easy, vo2.id: vo2},
        matched_planned_workout_ids={actual.id: easy.id},
    )

    tuesday = _day(packet, TUE)
    assert tuesday["dayStatus"] == "executed"
    assert [item["title"] for item in tuesday["planned"]] == ["Easy Z2"]
    assert tuesday["changes"][0]["direction"] == "out"
    assert tuesday["changes"][0]["workout"]["title"] == "VO2 Max"
    assert tuesday["changes"][0]["toDate"] == SAT.isoformat()
    assert [item["title"] for item in tuesday["executed"]] == ["Easy Z2 ride"]
    assert tuesday["executed"][0]["trainingLoad"] == 42.0
    assert tuesday["executed"][0]["matchedPlannedWorkout"]["title"] == "Easy Z2"
    assert all(item["title"] != "VO2 Max" for item in tuesday["executed"])

    saturday = _day(packet, SAT)
    assert [item["title"] for item in saturday["planned"]] == ["VO2 Max"]
    assert saturday["changes"][0]["direction"] == "in"
    assert saturday["changes"][0]["workout"]["title"] == "VO2 Max"
    assert packet["grounding"]["recommendationAttribution"].startswith("not inferred")


def test_explicit_skip_is_not_rest_or_execution() -> None:
    skipped = _workout(
        workout_date=WED,
        title="Sweet Spot",
        workout_type="bike_sweet_spot",
        status="skipped",
    )
    audit = _audit(
        analysis_type="workout_skipped",
        subject_date=WED,
        summary="Skipped Sweet Spot (2026-07-22).",
        linked_workout=skipped,
        tag=f"skip:{skipped.id}:v1",
    )

    packet = build_training_week_packet(
        start_date=MON,
        end_date=WED,
        timezone_name="Europe/London",
        planned_workouts=[skipped],
        action_audits=[audit],
        activities=[],
        workouts_by_id={skipped.id: skipped},
    )

    wednesday = _day(packet, WED)
    assert wednesday["dayStatus"] == "skipped"
    assert wednesday["planned"][0]["status"] == "skipped"
    assert wednesday["changes"][0]["action"] == "skipped"
    assert wednesday["executed"] == []


def test_unchanged_completed_session_matches_real_activity() -> None:
    planned = _workout(
        workout_date=TUE,
        title="Endurance",
        workout_type="bike_endurance",
        status="completed",
    )
    actual = _activity(start_utc=datetime(2026, 7, 21, 16, 30), title="Endurance")
    actual.user_id = planned.user_id

    packet = build_training_week_packet(
        start_date=MON,
        end_date=TUE,
        timezone_name="Europe/London",
        planned_workouts=[planned],
        action_audits=[],
        activities=[actual],
        workouts_by_id={planned.id: planned},
        matched_planned_workout_ids={actual.id: planned.id},
    )

    tuesday = _day(packet, TUE)
    assert tuesday["dayStatus"] == "executed"
    assert tuesday["changes"] == []
    assert tuesday["planned"][0]["title"] == "Endurance"
    assert tuesday["executed"][0]["matchedPlannedWorkout"]["id"] == str(planned.id)


@pytest.mark.asyncio
async def test_service_joins_active_plan_audit_activity_and_match(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    old_vo2 = _workout(
        workout_date=TUE,
        title="VO2 Max",
        workout_type="bike_vo2",
        active=False,
    )
    easy = _workout(
        workout_date=TUE,
        title="Easy Z2",
        workout_type="bike_endurance",
        status="completed",
        version=2,
    )
    moved_vo2 = _workout(
        workout_date=SAT,
        title="VO2 Max",
        workout_type="bike_vo2",
        version=2,
    )
    for workout in (old_vo2, easy, moved_vo2):
        workout.user_id = user_id
    actual = _activity(start_utc=datetime(2026, 7, 21, 17, 0), title="Easy Z2 ride")
    actual.user_id = user_id
    move_audit = _audit(
        analysis_type="workout_moved",
        subject_date=TUE,
        summary="Swapped 2026-07-21 and 2026-07-25.",
        linked_workout=moved_vo2,
        tag=f"swap:{old_vo2.id}:{SAT.isoformat()}",
    )
    move_audit.user_id = user_id
    match = Analysis(
        id=uuid.uuid4(),
        user_id=user_id,
        activity_id=actual.id,
        planned_workout_id=easy.id,
        analysis_type="post_workout",
        subject_date=TUE,
        generated_at_utc=datetime(2026, 7, 21, 18, 30),
        prompt_version="post-workout-test",
        context_packet={},
        output_markdown="Done.",
        raw_response={},
    )

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        profile = Profile(
            id=user_id,
            display_name="Training week test",
            pin_hash="x" * 60,
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(profile)
        # The fixture sets raw FK ids rather than ORM relationships, so make the
        # profile row visible before flushing its dependent rows.
        await session.flush()
        session.add_all([old_vo2, easy, moved_vo2, actual, move_audit, match])
        await session.commit()

        packet = await TrainingWeekService(session).build(profile, as_of=SAT)

    tuesday = _day(packet, TUE)
    assert tuesday["changes"][0]["workout"]["title"] == "VO2 Max"
    assert tuesday["executed"][0]["title"] == "Easy Z2 ride"
    assert tuesday["executed"][0]["matchedPlannedWorkout"]["title"] == "Easy Z2"
    saturday = _day(packet, SAT)
    assert saturday["changes"][0]["direction"] == "in"
