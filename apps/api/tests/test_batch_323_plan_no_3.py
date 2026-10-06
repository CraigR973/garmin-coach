"""Batch 323 — Plan No. 3, proposed in the app for Mark to accept, change or decline.

Plan No. 2 ended on Sun 18 Oct 2026 with nothing after it, and the app's plan builder had
never run: fixed build weeks, no FTP test, no strength progression, VO2 written "ERG off",
an FTP from a noisy drift signal, and a lock that kept only one session of a two-session
day. The next plan is now built from his last one (``services.next_plan``) to the ledger's
week-by-week table, and Home shows it from his taper week until he accepts or declines.
Wording: ``docs/drafts/2026-10-07-batch-323-wording.md``.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import (
    KnowledgeBase,
    PlanBlock,
    PlannedWorkout,
    WorkoutDeliveryProposal,
)
from src.models.profile import Profile, UserRole
from src.services.block_generator import (
    BLOCK_LOCK_SOURCE,
    GENERATED_BLOCK_SECTION,
    BlockGeneratorService,
)
from src.services.daily_loop_envelope import _next_plan
from src.services.next_plan import (
    DEFAULT_LONGEST_WEEK_MIN,
    LONG_RIDE_FLOOR_MIN,
    PLAN_NO_2_RHYTHM,
    WEEKS,
    ZONE2_FLOOR_MIN,
    PastSession,
    WeeklyRhythm,
    default_start,
    fit_week,
    longest_week_minutes,
    next_plan_draft,
    rhythm_from,
    week_sessions,
)
from src.services.verdict_grading import classify_planned_workout
from src.services.verdict_scaling import blocks_red_vo2
from src.services.vo2_progression import VO2_PROTOCOL_30_30, VO2_PROTOCOL_RONNESTAD_30_15
from src.services.workout_delivery import (
    IntervalsCreateResult,
    build_structured_workout_ir,
    validate_deliverable_bike_workout,
)

REPO = Path(__file__).resolve().parents[3]
DRAFT = REPO / "docs" / "drafts" / "2026-10-07-batch-323-wording.md"
PLAN_NO_2 = REPO / "apps" / "api" / "data" / "plans" / "plan_no2.json"

START = date(2026, 10, 19)  # Mon 19 Oct 2026, the day after Plan No. 2's last block


def _draft_text() -> str:
    return " ".join(DRAFT.read_text(encoding="utf-8").replace("**", "").split())


def _plan(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "start_date": START,
        "ftp_watts": 280,
        "athlete_name": "Mark",
        "generated_at_utc": datetime(2026, 10, 7, 7, 0),
        "plan_number": 3,
        "previous_name": "Plan No. 2",
    }
    kwargs.update(overrides)
    return next_plan_draft(**kwargs)


def _plan_no_2_sessions() -> list[PastSession]:
    """Plan No. 2 as he authored it (the reviewed JSON the import read), dated 20 Jul."""
    plan = json.loads(PLAN_NO_2.read_text(encoding="utf-8"))
    first_monday = date(2026, 7, 20)
    sessions = []
    for week in plan["weeks"]:
        for day in week["days"]:
            if day.get("rest"):
                continue
            sessions.append(
                PastSession(
                    workout_date=first_monday + timedelta(days=(week["week"] - 1) * 7 + day["dow"]),
                    workout_type=day["workout_type"],
                    title=day["title"],
                    minutes=int(day["duration_min"]),
                    block_type=week["block_type"],
                    week_number=int(week["week"]),
                )
            )
    return sessions


def _sessions_of(week: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    return [workout for workout in week["workouts"] if workout["kind"] == kind]


def _one(week: dict[str, Any], kind: str) -> dict[str, Any]:
    [only] = _sessions_of(week, kind)
    return only


# -- his week --------------------------------------------------------------------------------


def test_his_week_is_read_from_plan_no_2() -> None:
    sessions = _plan_no_2_sessions()
    rhythm = rhythm_from(sessions)
    assert rhythm == PLAN_NO_2_RHYTHM
    assert rhythm.to_packet() == {
        "strengthA": "Monday",
        "vo2": "Tuesday",
        "zone2": "Wednesday",
        "sweetSpot": "Thursday",
        "rest": "Friday",
        "sprints": "Saturday",
        "strengthB": "Saturday",
        "longRide": "Sunday",
    }
    # His longest week, as authored: week 5, 7 h 33.
    assert longest_week_minutes(sessions) == DEFAULT_LONGEST_WEEK_MIN == 453


def test_his_two_strength_days_are_his_commonest() -> None:
    """A strength session he added once, on a Wednesday, does not move his strength days."""
    sessions = _plan_no_2_sessions()
    stray = PastSession(
        workout_date=date(2026, 7, 22),
        workout_type="strength_maintenance",
        title="Extra dumbbells",
        minutes=20,
        block_type="build",
        week_number=1,
    )
    rhythm = rhythm_from([*sessions, stray])
    assert (rhythm.strength_a, rhythm.strength_b) == (0, 5)


def test_a_different_week_is_followed_and_an_unreadable_one_falls_back() -> None:
    shifted = [
        PastSession(
            workout_date=s.workout_date + timedelta(days=1)
            if s.workout_type in ("bike_vo2", "bike_sweet_spot")
            else s.workout_date,
            workout_type=s.workout_type,
            title=s.title,
            minutes=s.minutes,
            block_type=s.block_type,
            week_number=s.week_number,
        )
        for s in _plan_no_2_sessions()
    ]
    # VO2 moved to Wednesday collides with his Zone 2 day, so his week cannot be read.
    assert rhythm_from(shifted) == PLAN_NO_2_RHYTHM
    assert rhythm_from([]) == PLAN_NO_2_RHYTHM
    moved = WeeklyRhythm(vo2=3, sweet_spot=1)
    assert moved.is_valid()
    days = {session.kind: day for day, _slot, session in week_sessions(WEEKS[1], moved)}
    assert (days["vo2"], days["sweet_spot"]) == (3, 1)


def test_the_plan_starts_the_day_after_his_last_plan_ends() -> None:
    assert default_start(date(2026, 10, 7), date(2026, 10, 18)) == START
    # Long after his last plan, or with none, it starts next Monday.
    assert default_start(date(2026, 11, 4), date(2026, 10, 18)) == date(2026, 11, 9)
    assert default_start(date(2026, 10, 7), None) == date(2026, 10, 12)
    with pytest.raises(ValueError):
        _plan(start_date=date(2026, 10, 20))


def test_it_keeps_his_rhythm_and_starts_on_19_october() -> None:
    plan = _plan()
    assert (plan["startDate"], plan["endDate"]) == ("2026-10-19", "2027-01-17")
    assert plan["planName"] == "Plan No. 3"
    assert plan["ftpWatts"] == 280 and plan["progressionProposal"] is None
    for week in plan["weeks"]:
        start = date.fromisoformat(week["startDate"])
        weekdays = {
            workout["kind"]: (date.fromisoformat(workout["workoutDate"]) - start).days
            for workout in week["workouts"]
        }
        assert weekdays["strength_a"] == 0 and weekdays["strength_b"] == 5
        assert weekdays["sprints"] == 5 and weekdays["long"] == 6 and weekdays["zone2"] == 2
        tuesday = "test" if week["weekNumber"] == 1 else "vo2"
        assert weekdays[tuesday] == 1 and weekdays["sweet_spot"] == 3
        # Friday is always rest.
        assert all(workout["dayOffset"] != 4 for workout in week["workouts"])
        # Saturday carries two sessions, the ride first.
        saturday = sorted(
            (w for w in week["workouts"] if w["dayOffset"] == 5), key=lambda w: w["slot"]
        )
        assert [w["kind"] for w in saturday] == ["sprints", "strength_b"]
        assert [w["slot"] for w in saturday] == [0, 1]


# -- the ledger's table ----------------------------------------------------------------------

#: Batch 323's ledger table: (Tuesday minutes, Thursday minutes, Wednesday, Sunday, week).
LEDGER = (
    (40, 81, 75, 120, 414),
    (51, 91, 75, 120, 445),
    (41, 48, 60, 90, 324),
    (55, 94, 75, 120, 452),
    (65, 101, 55, 120, 449),
    (41, 48, 60, 90, 324),
    (54, 109, 45, 135, 451),
    (60, 111, 35, 135, 449),
    (41, 48, 60, 90, 324),
    (66, 111, 30, 135, 450),
    (66, 111, 30, 135, 450),
    (46, 58, 60, 90, 349),
    (30, 35, 45, 45, 235),
)


def test_every_week_is_the_ledgers() -> None:
    plan = _plan()
    for week, (tuesday, thursday, wednesday, sunday, total) in zip(
        plan["weeks"], LEDGER, strict=True
    ):
        by_day = {
            (w["dayOffset"], w["slot"]): int(w["plannedDurationMin"]) for w in week["workouts"]
        }
        assert (by_day[(1, 0)], by_day[(3, 0)], by_day[(2, 0)], by_day[(6, 0)]) == (
            tuesday,
            thursday,
            wednesday,
            sunday,
        ), week["weekNumber"]
        assert week["totalMin"] == total, week["weekNumber"]
    assert [w["blockType"] for w in plan["weeks"]] == [
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
        "consolidation",
        "taper",
    ]


def test_no_week_is_longer_than_his_longest() -> None:
    plan = _plan()
    assert max(week["totalMin"] for week in plan["weeks"]) <= 453


def test_a_lower_cap_trims_wednesday_first_then_the_long_ride() -> None:
    week7 = WEEKS[6]
    assert fit_week(week7, 453) is week7

    def total(week: Any) -> int:
        return sum(s.minutes for _day, _slot, s in week_sessions(week, PLAN_NO_2_RHYTHM))

    assert total(week7) == 451
    trimmed = fit_week(week7, 430)
    assert (trimmed.zone2_min, trimmed.long_ride.minutes, total(trimmed)) == (
        ZONE2_FLOOR_MIN,
        129,
        430,
    )
    deep = fit_week(week7, 300)
    assert (deep.zone2_min, deep.long_ride.minutes) == (ZONE2_FLOOR_MIN, LONG_RIDE_FLOOR_MIN)
    # A lighter last plan's cap holds in every week, and the draft records it.
    lighter = _plan(longest_week_min=420)
    assert lighter["basis"]["longestWeekMin"] == 420
    assert max(week["totalMin"] for week in lighter["weeks"]) <= 420


def test_week_1_has_the_ramp_test_on_tuesday() -> None:
    week1 = _plan()["weeks"][0]
    test = _one(week1, "test")
    assert (test["workoutDate"], test["title"]) == ("2026-10-20", "FTP Ramp Test")
    assert test["workoutType"] == "bike_threshold"
    assert _sessions_of(week1, "vo2") == []
    targets = [
        int(step["target"].rstrip("%"))
        for step in test["structuredWorkout"]["steps"]
        if step["label"].startswith("Ramp step")
    ]
    assert targets == list(range(50, 147, 6))
    assert all(
        step["minutes"] == 1
        for step in test["structuredWorkout"]["steps"]
        if step["label"].startswith("Ramp step")
    )


def _work_minutes(vo2: dict[str, Any]) -> float:
    sets = [s for s in vo2["structuredWorkout"]["steps"] if " set " in s["label"]]
    reps = sum(int(s["pattern"].split(" x ")[0]) for s in sets)
    return reps * 0.5


def test_each_build_week_progresses_on_the_last() -> None:
    builds = [week for week in _plan()["weeks"] if week["blockType"] == "build"]
    assert [week["weekNumber"] for week in builds] == [1, 2, 4, 5, 7, 8, 10, 11]
    vo2s = [_one(week, "vo2") for week in builds[1:]]
    work = [_work_minutes(vo2) for vo2 in vo2s]
    assert work == [10, 12, 15, 16, 18, 20, 20]
    protocols = [vo2["structuredWorkout"]["vo2Protocol"] for vo2 in vo2s]
    assert protocols == [VO2_PROTOCOL_30_30] * 3 + [VO2_PROTOCOL_RONNESTAD_30_15] * 4
    # Week 11 repeats week 10's work at a higher target.
    assert "@ 125%" in vo2s[-2]["title"] and "@ 128%" in vo2s[-1]["title"]

    sweet = [_one(week, "sweet_spot") for week in builds]
    dose = []
    for session in sweet:
        main = next(
            s
            for s in session["structuredWorkout"]["steps"]
            if "pattern" in s and "Sweet" in s["label"]
        )
        reps, rest = main["pattern"].split(" x ")
        minutes = int(rest.split("min")[0])
        dose.append((int(reps) * minutes, int(main["target"].rstrip("%"))))
    assert [minutes for minutes, _pct in dose] == [50, 60, 60, 70, 75, 80, 80, 80]
    assert [pct for _m, pct in dose] == [89, 89, 90, 90, 90, 90, 91, 92]
    products = [minutes * pct for minutes, pct in dose]
    assert all(later >= earlier for earlier, later in zip(products, products[1:], strict=False))
    assert products[-1] > products[0]

    longs = [int(_one(week, "long")["plannedDurationMin"]) for week in builds]
    assert longs == [120, 120, 120, 120, 135, 135, 135, 135]


def test_two_loaded_strength_sessions_every_week_that_progress() -> None:
    plan = _plan()
    for week in plan["weeks"]:
        a, b = _one(week, "strength_a"), _one(week, "strength_b")
        assert a["title"] == "Dumbbells A (legs and back)"
        assert b["title"] == "Dumbbells B (upper body)"
        for session in (a, b):
            assert session["workoutType"] == "strength_maintenance"
            assert "Dumbbells" in session["intensityTarget"]
    doses = [_one(week, "strength_a")["intensityTarget"] for week in plan["weeks"]]
    assert doses[0] == "Dumbbells 2 × 12" and doses[1] == "Dumbbells 3 × 12"
    assert doses[10].startswith("Dumbbells 4 × 6–8")
    summary = _one(plan["weeks"][0], "strength_a")["structuredWorkout"]["summary"]
    assert summary.startswith("Goblet squat, Romanian deadlift")
    assert "Rest about a minute between sets." in summary


def test_every_ride_is_deliverable_whole_minutes_and_never_erg_off() -> None:
    plan = _plan()
    rides = 0
    for week in plan["weeks"]:
        for workout in week["workouts"]:
            text = json.dumps(workout).lower()
            assert "erg off" not in text and '"ergmode": "off"' not in text
            structured = workout["structuredWorkout"]
            if structured.get("format") != "bike":
                continue
            steps = validate_deliverable_bike_workout(
                structured, workout["intensityTarget"], context=workout["title"]
            )
            assert sum(int(step["durationSec"]) for step in steps) == (
                int(workout["plannedDurationMin"]) * 60
            ), workout["title"]
            rides += 1
    assert rides == 13 * 5


def _planned(workout: dict[str, Any]) -> PlannedWorkout:
    return PlannedWorkout(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        workout_date=date.fromisoformat(workout["workoutDate"]),
        version=1,
        title=workout["title"],
        workout_type=workout["workoutType"],
        status="planned",
        is_active=True,
        planned_duration_min=workout["plannedDurationMin"],
        intensity_target=workout["intensityTarget"],
        structured_workout=workout["structuredWorkout"],
        source="test",
    )


def test_a_red_morning_never_sends_vo2_or_the_test_to_zwift() -> None:
    """The generator's invariant: Red never VO2. The test reaches 146% of FTP too."""
    plan = _plan()
    checked = 0
    for week in plan["weeks"]:
        for workout in week["workouts"]:
            if workout["kind"] not in ("vo2", "test"):
                continue
            ir = build_structured_workout_ir(_planned(workout), ftp_watts=280)
            assert blocks_red_vo2("Red", ir), workout["title"]
            assert classify_planned_workout(_planned(workout)).is_hard, workout["title"]
            checked += 1
    assert checked == 13


def test_the_why_this_plan_note_is_the_signed_off_words() -> None:
    why = _plan()["whyThisPlan"]
    assert why == [
        "It keeps your week from Plan No. 2: dumbbells on Monday, VO₂ on Tuesday, Zone 2 on "
        "Wednesday, sweet spot on Thursday, Friday off, Zone 2 with sprints and dumbbells on "
        "Saturday, and the long ride on Sunday.",
        "Week 1 opens with an FTP ramp test on Tuesday 20 October. Ride it in ERG until you "
        "can't hold the step. Your new FTP is three-quarters of the best minute you held: set "
        "it in Zwift, and every session follows, because each target is a percentage of FTP.",
        "Each build week asks a little more than the one before: sweet spot from 2 × 25 minutes "
        "to 2 × 40, VO₂ from 30/30s to 30/15s, and the long ride from 2 hours to 2 hours 15.",
        "Two dumbbell sessions a week, on Monday and Saturday, legs as well as arms now, "
        "getting heavier through the plan. Recovery weeks go lighter.",
        "No week is longer than the longest week of Plan No. 2 (7 h 33).",
        "Christmas Day and New Year's Day fall on your Friday rest days.",
        "Nothing changes until you accept it, and you can change any day first.",
    ]
    draft = _draft_text()
    assert "signed off on Mark's behalf under Craig's delegation of 6 Oct 2026" in draft
    for line in why:
        assert line in draft, line


def test_a_holiday_off_the_rest_day_is_named() -> None:
    why = _plan(start_date=date(2026, 11, 2))["whyThisPlan"]
    # Starting 2 Nov, the plan still covers both; both still fall on a Friday.
    assert "Christmas Day and New Year's Day fall on your Friday rest days." in why
    later = _plan(start_date=date(2027, 10, 18), plan_number=4, previous_name="Plan No. 3")
    assert "Christmas Day is a Saturday: change that day if you need to." in later["whyThisPlan"]


# -- on Postgres ------------------------------------------------------------------------------


async def _profile(session: AsyncSession, *, ftp: int = 280) -> Profile:
    player = Profile(
        id=uuid.uuid4(),
        display_name="Plan Three",
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
            content={"athleteName": "Mark", "ftpWatts": ftp},
            updated_by_profile_id=player.id,
        )
    )
    await session.commit()
    return player


async def _seed_plan_no_2(session: AsyncSession, player: Profile, first_monday: date) -> None:
    """Plan No. 2 as production holds it: 13 "PN2" blocks and the import's sessions."""
    plan = json.loads(PLAN_NO_2.read_text(encoding="utf-8"))
    for week in plan["weeks"]:
        start = first_monday + timedelta(days=(week["week"] - 1) * 7)
        block = PlanBlock(
            user_id=player.id,
            name=f"PN2 W{week['week']:02d} {week['label']}",
            version=1,
            sequence_index=week["week"],
            block_type=week["block_type"],
            start_date=start,
            end_date=start + timedelta(days=6),
            goals_json={},
            raw_plan={},
        )
        session.add(block)
        await session.flush()
        versions: dict[date, int] = {}
        for day in week["days"]:
            if day.get("rest"):
                continue
            workout_date = start + timedelta(days=day["dow"])
            versions[workout_date] = versions.get(workout_date, 0) + 1
            session.add(
                PlannedWorkout(
                    user_id=player.id,
                    plan_block_id=block.id,
                    workout_date=workout_date,
                    version=versions[workout_date],
                    title=day["title"],
                    workout_type=day["workout_type"],
                    status="planned",
                    is_active=True,
                    planned_duration_min=day["duration_min"],
                    intensity_target=day["intensity_target"],
                    structured_workout=day["structured_workout"],
                    source="plan_no2_import",
                )
            )
    await session.commit()


#: Plan No. 2, seeded well before any plausible "today", so the seeded default plan a
#: fresh profile gets from the real current week never overlaps it.
SEEDED_FIRST_MONDAY = date(2026, 3, 2)
SEEDED_NEXT_START = SEEDED_FIRST_MONDAY + timedelta(days=13 * 7)


@pytest.mark.asyncio
async def test_on_postgres_the_draft_is_built_from_his_last_plan(db_conn: AsyncConnection) -> None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = await _profile(session)
        await _seed_plan_no_2(session, player, SEEDED_FIRST_MONDAY)
        service = BlockGeneratorService(session)
        previous = await service.previous_plan(player.id)
        assert previous is not None
        assert previous.number == 2
        assert previous.end_date == SEEDED_NEXT_START - timedelta(days=1)
        assert previous.longest_week_min == 453
        assert rhythm_from(previous.sessions) == PLAN_NO_2_RHYTHM

        draft = await service.generate(player, start_date=SEEDED_NEXT_START)
        assert draft["planName"] == "Plan No. 3"
        assert draft["basis"]["previousPlan"] == "Plan No. 2"
        assert draft["basis"]["longestWeekMin"] == 453
        assert draft["ftpWatts"] == 280
        assert draft["whyThisPlan"][0].startswith("It keeps your week from Plan No. 2:")
        row = await session.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.user_id == player.id,
                KnowledgeBase.section == GENERATED_BLOCK_SECTION,
                KnowledgeBase.is_active.is_(True),
            )
        )
        assert row is not None and row.content["status"] == "draft"
        # Generating writes no plan: nothing reaches his plan or Zwift until he accepts.
        new_blocks = await session.scalar(
            select(func.count())
            .select_from(PlanBlock)
            .where(PlanBlock.user_id == player.id, PlanBlock.name.like("PN3%"))
        )
        assert new_blocks == 0


class _FakeIntervalsClient:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    async def create_workout_event(self, payload: dict[str, Any]) -> IntervalsCreateResult:
        self.payloads.append(payload)
        event_id = f"evt_{len(self.payloads)}"
        return IntervalsCreateResult(event_id=event_id, raw_response={"id": event_id})

    async def update_workout_event(
        self, event_id: str, payload: dict[str, Any]
    ) -> IntervalsCreateResult:
        return IntervalsCreateResult(event_id=event_id, raw_response={"id": event_id})

    async def delete_workout_event(self, event_id: str) -> None:
        return None


@pytest.mark.asyncio
async def test_on_postgres_accepting_writes_the_plan_and_pushes_its_rides(
    db_conn: AsyncConnection,
) -> None:
    fake = _FakeIntervalsClient()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = await _profile(session)
        await _seed_plan_no_2(session, player, SEEDED_FIRST_MONDAY)
        await BlockGeneratorService(session).generate(player, start_date=SEEDED_NEXT_START)
        result = await BlockGeneratorService(session, intervals_client=fake).lock(player)
        assert (result.blocks_created, result.workouts_written) == (13, 13 * 7)

        blocks = (
            (
                await session.execute(
                    select(PlanBlock)
                    .where(PlanBlock.user_id == player.id, PlanBlock.name.like("PN3%"))
                    .order_by(PlanBlock.sequence_index)
                )
            )
            .scalars()
            .all()
        )
        assert [block.name for block in blocks][:2] == ["PN3 W01 TEST + BUILD", "PN3 W02 BUILD"]
        # Both of a Saturday's sessions are written and active: the ride, then strength.
        saturday = SEEDED_NEXT_START + timedelta(days=5)
        rows = (
            (
                await session.execute(
                    select(PlannedWorkout)
                    .where(
                        PlannedWorkout.user_id == player.id,
                        PlannedWorkout.workout_date == saturday,
                    )
                    .order_by(PlannedWorkout.version)
                )
            )
            .scalars()
            .all()
        )
        assert [(row.title, row.is_active, row.version) for row in rows] == [
            ("Z2 + Neuromuscular", True, 1),
            ("Dumbbells B (upper body)", True, 2),
        ]
        assert all(row.source == BLOCK_LOCK_SOURCE for row in rows)
        # Every ride went to Zwift without a per-ride approval (push-on-plan-set, #99).
        proposals = (
            (
                await session.execute(
                    select(WorkoutDeliveryProposal).where(
                        WorkoutDeliveryProposal.user_id == player.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(proposals) == len(fake.payloads) == 13 * 5
        assert all(proposal.status == "pushed" for proposal in proposals)


@pytest.mark.asyncio
async def test_on_postgres_declining_writes_nothing(db_conn: AsyncConnection) -> None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = await _profile(session)
        await _seed_plan_no_2(session, player, SEEDED_FIRST_MONDAY)
        await BlockGeneratorService(session).generate(player, start_date=SEEDED_NEXT_START)
        before_rows = await session.scalar(
            select(func.count())
            .select_from(PlannedWorkout)
            .where(PlannedWorkout.user_id == player.id)
        )
        await BlockGeneratorService(session).discard(player)

        after_rows = await session.scalar(
            select(func.count())
            .select_from(PlannedWorkout)
            .where(PlannedWorkout.user_id == player.id)
        )
        assert after_rows == before_rows
        new_blocks = await session.scalar(
            select(func.count())
            .select_from(PlanBlock)
            .where(PlanBlock.user_id == player.id, PlanBlock.name.like("PN3%"))
        )
        assert new_blocks == 0
        # The declined draft stays as the record, set aside.
        row = await session.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.user_id == player.id,
                KnowledgeBase.section == GENERATED_BLOCK_SECTION,
            )
        )
        assert row is not None and row.is_active is False


@pytest.mark.asyncio
async def test_on_postgres_home_shows_the_card_only_with_a_draft_as_his_plan_ends(
    db_conn: AsyncConnection,
) -> None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = await _profile(session)
        await _seed_plan_no_2(session, player, SEEDED_FIRST_MONDAY)
        taper = SEEDED_NEXT_START - timedelta(days=3)  # inside the 13th block
        mid_plan = SEEDED_FIRST_MONDAY + timedelta(days=30)
        after = SEEDED_NEXT_START + timedelta(days=2)  # no block covers it

        # No draft yet: no card anywhere.
        for day, boundary in ((taper, True), (after, False)):
            assert (
                await _next_plan(db=session, user_id=player.id, day=day, at_block_boundary=boundary)
                is None
            )

        await BlockGeneratorService(session).generate(player, start_date=SEEDED_NEXT_START)
        card = await _next_plan(session, player.id, taper, at_block_boundary=True)
        assert card is not None
        assert (card.planName, card.startDate, card.endDate) == (
            "Plan No. 3",
            SEEDED_NEXT_START.isoformat(),
            (SEEDED_NEXT_START + timedelta(days=90)).isoformat(),
        )
        assert await _next_plan(session, player.id, after, at_block_boundary=False) is not None
        # Mid-plan, with a draft: no card yet.
        assert await _next_plan(session, player.id, mid_plan, at_block_boundary=False) is None

        await BlockGeneratorService(session).discard(player)
        assert await _next_plan(session, player.id, taper, at_block_boundary=True) is None
