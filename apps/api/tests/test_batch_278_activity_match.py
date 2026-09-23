"""Batch 278 — an activity is not recorded as a session it was not.

``complete_matched_planned_workout`` matched on local date + workout category and
nothing else, so whatever bike row sat on the date was flipped to ``completed`` by
whatever bike activity arrived. Mark surfaced both halves on 22 September 2026: a
Zone-2 ride recorded as ``VO₂ (5 × 2:30 @ 119%)``, and a ``Daily Bodyweight
Workout`` recorded as ``Dumbbells (full-body)``.

Every fixture below is a real production shape. The ride numbers are his actual
22 September activity (normalised power 186 W against FTP 280) and the
prescriptions are the exact ``structured_workout`` JSON that sat on those rows.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import Activity, KnowledgeBase, PlannedWorkout
from src.models.profile import Profile, UserRole
from src.services.post_activity_analysis import prepare_post_activity_read
from src.services.verdict_scaling import ir_sustained_work_pct
from src.services.workout_delivery import build_structured_workout_ir
from src.services.workout_match import (
    EXECUTED_ENDURANCE_CEILING,
    bike_material_difference,
    strength_material_difference,
)

FTP_WATTS = 280

# The three prescriptions that mattered on 22 September, byte-for-byte from
# ``coach.planned_workouts.structured_workout``.
VO2_PRESCRIPTION = {
    "steps": [
        {"ramp": [55, 80], "label": "Warm-up ramp 55→80%", "minutes": 10},
        {
            "label": "Primer 2×30s @100% / 55%",
            "target": "100%",
            "pattern": "2 x 30s / 30s @55%",
            "cadenceRpm": 95,
        },
        {"label": "Warm-up @72%", "target": "72%", "minutes": 3},
        {"label": "Warm-up @55%", "target": "55%", "minutes": 2},
        {
            "block": {
                "rest": {"powerPct": 60, "durationSec": 210},
                "work": {"powerPct": 119, "cadenceRpm": 95, "durationSec": 150},
                "repeat": 5,
            },
            "label": "VO₂ 5×2:30 @119%",
        },
        {"ramp": [70, 45], "label": "Cool-down ramp", "minutes": 10},
    ],
    "format": "bike",
    "summary": "WarmUp v1.3 · Main 5 × 2:30 @119% (3:30 @60% recover) · CoolDown 10 min ramp",
}

Z2_NEUROMUSCULAR_PRESCRIPTION = {
    "steps": [
        {"ramp": [50, 75], "label": "Warm-up ramp 50→75%", "minutes": 5},
        {
            "label": "Z2 @65% + cadence surges (100–105 rpm)",
            "target": "65%",
            "pattern": "5 x 1min / 5min @65%",
            "cadenceRpm": 102,
        },
        {
            "label": "Neuromuscular sprints @185%",
            "target": "185%",
            "pattern": "6 x 12s / 168s @55%",
        },
        {"label": "Cool-down @50%", "target": "50%", "minutes": 5},
    ],
    "format": "bike",
    "summary": "5 min ramp → 30 min @65% → 6 × (12 s @185% + 2:48 @55%) → 5 min @50%",
}

DUMBBELL_PRESCRIPTION = {
    "steps": [
        {
            "label": "Dumbbell circuit (8 exercises × 3 sets)",
            "target": "30s work / 15s rest",
            "minutes": 22,
        }
    ],
    "format": "strength",
    "summary": "~22 min full-body dumbbell circuit — 3 sets each of biceps curl, "
    "shoulder press, lying triceps extension. 30s work / 15s rest.",
}

BODYWEIGHT_PRESCRIPTION = {
    "steps": [
        {
            "label": "Bodyweight circuit (5 exercises × 3 rounds)",
            "target": "10 reps each",
            "minutes": 15,
        }
    ],
    "format": "strength",
    "summary": "~15 min bodyweight circuit — 3 rounds of squat, dead bug, "
    "mountain climber, glute bridge, and push-up.",
}


def _planned(
    title: str,
    workout_type: str,
    structured: dict[str, object],
    *,
    intensity_target: str | None = None,
    user_id: uuid.UUID | None = None,
) -> PlannedWorkout:
    return PlannedWorkout(
        id=uuid.uuid4(),
        user_id=user_id or uuid.uuid4(),
        workout_date=date(2026, 9, 22),
        version=1,
        title=title,
        workout_type=workout_type,
        status="planned",
        is_active=True,
        intensity_target=intensity_target,
        structured_workout=structured,
    )


def _ride(
    name: str = "Indoor Cycling",
    *,
    normalized_power_watts: int | None = 186,
) -> Activity:
    """Mark's real 22 September ride: 58 min, avg 176 W, max 517 W, NP 186 W."""
    return Activity(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        garmin_activity_id=1,
        activity_name=name,
        activity_type="indoor_cycling",
        start_utc=datetime(2026, 9, 22, 10, 57),
        duration_sec=3480.5,
        avg_power_watts=176,
        max_power_watts=517,
        normalized_power_watts=normalized_power_watts,
        avg_heart_rate_bpm=111,
        max_heart_rate_bpm=125,
        raw_summary={},
    )


def _strength_activity(name: str, duration_sec: float = 630.6) -> Activity:
    return Activity(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        garmin_activity_id=2,
        activity_name=name,
        activity_type="strength_training",
        start_utc=datetime(2026, 9, 22, 8, 9),
        duration_sec=duration_sec,
        exclude_from_recovery=True,
        raw_summary={},
    )


# -- the bike rule -----------------------------------------------------------


def test_a_zone_2_ride_is_not_the_vo2_session_it_was_recorded_as() -> None:
    deviation = bike_material_difference(
        _planned("VO₂ (5 × 2:30 @ 119%)", "bike_vo2", VO2_PRESCRIPTION),
        _ride(),
        ftp_watts=FTP_WATTS,
    )
    assert deviation is not None
    assert deviation["kind"] == "intensity_mismatch"
    assert deviation["prescribed"]["sustainedWorkPctFtp"] == 119
    assert deviation["executed"]["normalisedFractionOfFtp"] == 0.664


def test_the_ride_he_actually_did_is_still_recorded_as_completed() -> None:
    """The same ride against its own prescription. The 185% sprints last 12 s, so
    277's alactic rule keeps this reading as the 65% endurance session it is —
    without that, every ``Z2 + Neuromuscular`` day would be flagged."""
    planned = _planned("Z2 + Neuromuscular", "bike_endurance", Z2_NEUROMUSCULAR_PRESCRIPTION)
    assert ir_sustained_work_pct(build_structured_workout_ir(planned, ftp_watts=FTP_WATTS)) == 65
    assert bike_material_difference(planned, _ride(), ftp_watts=FTP_WATTS) is None


@pytest.mark.parametrize(
    ("label", "normalized_power_watts"),
    [
        # Every genuinely-performed hard session since 15 June 2026 sat at or above
        # 0.754 of FTP. These are the two closest to the threshold.
        ("Sweet Spot Touch, 2026-07-02", 211),
        ("Sweet Spot Light 1×20 @89%, 2026-09-17", 218),
    ],
)
def test_a_real_attempt_at_a_hard_session_is_never_called_a_deviation(
    label: str,
    normalized_power_watts: int,
) -> None:
    assert normalized_power_watts / FTP_WATTS >= EXECUTED_ENDURANCE_CEILING, label
    assert (
        bike_material_difference(
            _planned("VO₂ (5 × 2:30 @ 119%)", "bike_vo2", VO2_PRESCRIPTION),
            _ride(normalized_power_watts=normalized_power_watts),
            ftp_watts=FTP_WATTS,
        )
        is None
    )


def test_an_endurance_prescription_makes_no_claim_at_all() -> None:
    assert (
        bike_material_difference(
            _planned("Long Z2", "bike_endurance", Z2_NEUROMUSCULAR_PRESCRIPTION),
            _ride(normalized_power_watts=120),
            ftp_watts=FTP_WATTS,
        )
        is None
    )


@pytest.mark.parametrize(
    ("normalized_power_watts", "ftp_watts"),
    [(None, FTP_WATTS), (186, None), (186, 0)],
)
def test_the_bike_rule_abstains_rather_than_guessing_a_denominator(
    normalized_power_watts: int | None,
    ftp_watts: int | None,
) -> None:
    assert (
        bike_material_difference(
            _planned("VO₂ (5 × 2:30 @ 119%)", "bike_vo2", VO2_PRESCRIPTION),
            _ride(normalized_power_watts=normalized_power_watts),
            ftp_watts=ftp_watts,
        )
        is None
    )


def test_a_prescription_written_as_prose_abstains() -> None:
    """The 8 July 2026 row's target was ``VO₂ (see prescription)``, which resolves to
    no percentage at all. A rule that cannot read the prescription says nothing."""
    planned = _planned(
        "VO₂ (5 × 2 min @ 120%)",
        "bike_vo2",
        {
            "steps": [
                {
                    "label": "VO₂ (5 × 2 min @ 120%)",
                    "target": "VO₂ (see prescription)",
                    "minutes": 60,
                }
            ],
            "format": "bike",
        },
    )
    assert bike_material_difference(planned, _ride(), ftp_watts=FTP_WATTS) is None


# -- the strength rule -------------------------------------------------------


def test_a_bodyweight_workout_is_not_the_dumbbell_session_mark_flagged() -> None:
    deviation = strength_material_difference(
        _planned("Dumbbells (full-body)", "strength_maintenance", DUMBBELL_PRESCRIPTION),
        _strength_activity("Daily Bodyweight Workout"),
    )
    assert deviation is not None
    assert deviation["kind"] == "modality_mismatch"
    assert deviation["prescribed"]["modality"] == "weighted"
    assert deviation["executed"]["modality"] == "bodyweight"


@pytest.mark.parametrize(
    ("planned_title", "prescription", "activity_name"),
    [
        ("Dumbbells (full-body)", DUMBBELL_PRESCRIPTION, "Dumbbell Workout"),
        ("Bodyweight", BODYWEIGHT_PRESCRIPTION, "Daily Bodyweight Workout"),
        ("Bodyweight", BODYWEIGHT_PRESCRIPTION, "Weekly Bodyweight Workout"),
    ],
)
def test_a_strength_session_that_agrees_with_its_prescription_still_completes(
    planned_title: str,
    prescription: dict[str, object],
    activity_name: str,
) -> None:
    assert (
        strength_material_difference(
            _planned(planned_title, "strength_maintenance", prescription),
            _strength_activity(activity_name),
        )
        is None
    )


@pytest.mark.parametrize(
    ("planned_title", "prescription", "activity_name"),
    [
        # The activity names no modality — 86 of Mark's strength activities are
        # ``Recovery Morning Routine`` and the app cannot tell what is in one.
        ("Bodyweight", BODYWEIGHT_PRESCRIPTION, "Recovery Morning Routine"),
        # The prescription names none.
        ("Strength maintenance", {}, "Daily Bodyweight Workout"),
        ("Recovery Strength + Mobility", {}, "Dumbbell Workout"),
    ],
)
def test_the_strength_rule_claims_nothing_when_either_side_is_silent(
    planned_title: str,
    prescription: dict[str, object],
    activity_name: str,
) -> None:
    assert (
        strength_material_difference(
            _planned(planned_title, "strength_maintenance", prescription),
            _strength_activity(activity_name),
        )
        is None
    )


# -- the matcher, end to end -------------------------------------------------


async def _seed(session: AsyncSession, *, ftp_watts: int | None = FTP_WATTS) -> Profile:
    player = Profile(
        id=uuid.uuid4(),
        display_name="Batch 278",
        role=UserRole.player,
        timezone="Europe/London",
        is_active=True,
    )
    session.add(player)
    await session.flush()
    if ftp_watts is not None:
        session.add(
            KnowledgeBase(
                user_id=player.id,
                section="profile",
                version=1,
                is_active=True,
                source="test",
                content={"ftpWatts": ftp_watts},
            )
        )
        await session.flush()
    return player


def _persisted_ride(user_id: uuid.UUID, garmin_id: int = 9_000_001) -> Activity:
    ride = _ride()
    ride.user_id = user_id
    ride.garmin_activity_id = garmin_id
    return ride


@pytest.mark.asyncio
async def test_the_22_sep_ride_no_longer_completes_the_vo2_row(
    db_conn: AsyncConnection,
) -> None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = await _seed(session)
        workout = _planned(
            "VO₂ (5 × 2:30 @ 119%)",
            "bike_vo2",
            VO2_PRESCRIPTION,
            user_id=player.id,
        )
        activity = _persisted_ride(player.id)
        session.add_all([workout, activity])
        await session.flush()

        prepared = await prepare_post_activity_read(session, player, activity, commit=False)

    assert prepared.kind == "ride"
    assert workout.status == "planned"
    assert prepared.planned_workout_id is None


@pytest.mark.asyncio
async def test_the_ride_he_did_do_still_completes_its_row(
    db_conn: AsyncConnection,
) -> None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = await _seed(session)
        workout = _planned(
            "Z2 + Neuromuscular",
            "bike_endurance",
            Z2_NEUROMUSCULAR_PRESCRIPTION,
            user_id=player.id,
        )
        activity = _persisted_ride(player.id, garmin_id=9_000_002)
        session.add_all([workout, activity])
        await session.flush()

        prepared = await prepare_post_activity_read(session, player, activity, commit=False)

    assert workout.status == "completed"
    assert prepared.planned_workout_id == workout.id


@pytest.mark.asyncio
async def test_the_bodyweight_session_no_longer_completes_the_dumbbell_row(
    db_conn: AsyncConnection,
) -> None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = await _seed(session)
        workout = _planned(
            "Dumbbells (full-body)",
            "strength_maintenance",
            DUMBBELL_PRESCRIPTION,
            user_id=player.id,
        )
        activity = _strength_activity("Daily Bodyweight Workout")
        activity.user_id = player.id
        activity.garmin_activity_id = 9_000_003
        session.add_all([workout, activity])
        await session.flush()

        prepared = await prepare_post_activity_read(session, player, activity, commit=False)

    assert prepared.kind == "strength"
    assert workout.status == "planned"
    assert prepared.planned_workout_id is None


@pytest.mark.asyncio
async def test_the_dumbbell_session_arriving_later_still_claims_the_row(
    db_conn: AsyncConnection,
) -> None:
    """31 Aug, 9 Sep and 14 Sep each held both activities against one dumbbell row.
    The bodyweight one must not take it, and the dumbbell one must."""
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = await _seed(session)
        workout = _planned(
            "Dumbbells (full-body)",
            "strength_maintenance",
            DUMBBELL_PRESCRIPTION,
            user_id=player.id,
        )
        bodyweight = _strength_activity("Daily Bodyweight Workout")
        bodyweight.user_id = player.id
        bodyweight.garmin_activity_id = 9_000_004
        dumbbells = _strength_activity("Dumbbell Workout", duration_sec=1291)
        dumbbells.user_id = player.id
        dumbbells.garmin_activity_id = 9_000_005
        session.add_all([workout, bodyweight, dumbbells])
        await session.flush()

        first = await prepare_post_activity_read(session, player, bodyweight, commit=False)
        second = await prepare_post_activity_read(session, player, dumbbells, commit=False)

    assert first.planned_workout_id is None
    assert second.planned_workout_id == workout.id
    assert workout.status == "completed"


@pytest.mark.asyncio
async def test_an_unplanned_ride_is_still_a_no_match_not_a_deviation(
    db_conn: AsyncConnection,
) -> None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = await _seed(session)
        activity = _persisted_ride(player.id, garmin_id=9_000_006)
        session.add(activity)
        await session.flush()

        prepared = await prepare_post_activity_read(session, player, activity, commit=False)

    assert prepared.planned_workout_id is None
