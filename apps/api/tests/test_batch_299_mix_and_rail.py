"""Batch 299 — the weekly mix and the delivery rail follow the session actions.

Under the graded verdict a morning decides what happens to each session: eased a zone
at full length (``ease_hard``), held with its targets (``hold_targets``, the light-week
hold), moved or held (``move_or_hold``), or dropped (a Red recovery spin, a shortened
ride, or a floor's day off). Two things still read only the colour:

* the weekly mix called any Amber or Red "a Sweet Spot session short this week" beside a
  plan line that kept the session, so W12 and W13 would have said both at once;
* the delivery rail fell back to the colour for a ride with no action, so on 1 Oct 2026,
  a holiday rest day, it proposed an eased version of the Sweet Spot the holiday had
  paused. That proposal is still ``proposed`` in production.

These tests pin both to the actions. The ladder reads as before, apart from the rail's
two guards (a rest-day morning and a skipped or completed session), which hold under
either engine. Mark-facing wording signed off by Craig on Mark's behalf on 1 Oct 2026
(``docs/drafts/2026-10-01-batch-298-wording.md``, section 6).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from src.models.coaching import Analysis, PlannedWorkout, WorkoutDeliveryProposal
from src.models.profile import Profile
from src.services.executable_coaching import ExecutableCoachingService, MorningContext
from src.services.morning_analysis import (
    GRADED_PROMPT_VERSION,
    GRADED_SYSTEM_PROMPT,
    LADDER_SYSTEM_PROMPT,
)
from src.services.verdict_grading import (
    ENGINE_GRADED,
    stored_actions,
    stored_engine,
    stored_rest_day,
    stored_seen_workouts,
)
from src.services.weekly_mix import (
    DROPPING_ACTIONS,
    MIX_SWEET_SPOT,
    MIX_VO2,
    MixSession,
    WeeklyMixService,
    mix_for_verdict,
)
from tests.test_executable_coaching import SWEET_SPOT_STRUCTURED, _seed_profile
from tests.test_weekly_mix import _planned, _profile

# W12 CONSOLIDATION, Mark's first week back: Z2 Wed 7, Sweet Spot Thu 8, Z2 Sat 10, Sun 11.
WED = date(2026, 10, 7)
THU = date(2026, 10, 8)
SAT = date(2026, 10, 10)
SUN = date(2026, 10, 11)
SWEET_SPOT_ID = "8c0f6c55-2f39-4d55-9a37-3c1d9a0e0808"
VO2_ID = "1b0c3e3a-6a2f-4a8e-8f43-6f4e0b6d0808"

EASED_LINE = (
    "Today's Sweet Spot session is eased, not lost: its hard intervals drop a zone and it "
    "keeps its full length."
)

#: 1 Oct 2026's stored morning, as production wrote it (read-only, 1 Oct): a holiday rest
#: day, graded Amber, no session actions, and the Sweet Spot the holiday had paused.
ONE_OCT_SWEET_SPOT_ID = "12774155-bf09-4f06-8b3c-43e7e797c081"
ONE_OCT_PACKET: dict[str, Any] = {
    "restDay": {
        "reason": "holiday",
        "isRestDay": True,
        "insideHolidayWindow": True,
        "allPlannedWorkoutsSkipped": True,
    },
    "plannedWorkouts": [
        {
            "id": ONE_OCT_SWEET_SPOT_ID,
            "title": "Sweet Spot (3 × 18 min @ 89%)",
            "status": "skipped",
            "source": "holiday_pause",
            "version": 2,
            "workoutDate": "2026-10-01",
            "workoutType": "bike_sweet_spot",
        }
    ],
    "verdict": {
        "engine": "graded",
        "status": "Amber",
        "held": False,
        "isRestDay": True,
        "graded": {"actions": []},
        "weeklyMix": {"shortfall": None},
    },
}


def _w12(*, today_type: str = "bike_sweet_spot", today_id: str = SWEET_SPOT_ID) -> list[Any]:
    return [
        MixSession(workout_date=WED, workout_type="bike_endurance", completed=True),
        MixSession(workout_date=THU, workout_type=today_type, completed=False, workout_id=today_id),
        MixSession(workout_date=SAT, workout_type="bike_endurance", completed=False),
        MixSession(workout_date=SUN, workout_type="bike_endurance", completed=False),
    ]


def _mix(status: str, actions: dict[str, str] | None, **kwargs: Any) -> Any:
    sessions = kwargs.pop("sessions", None) or _w12()
    return mix_for_verdict(
        sessions,
        [],
        subject_date=THU,
        verdict_status=status,
        swap=None,
        session_actions=actions,
        **kwargs,
    )


def _ride(
    workout_id: str | None = None, *, status: str = "planned", day: date = THU
) -> PlannedWorkout:
    return PlannedWorkout(
        id=uuid.UUID(workout_id) if workout_id else uuid.uuid4(),
        user_id=uuid.uuid4(),
        workout_date=day,
        version=1,
        title="Sweet Spot (1 × 30 min @ 89%)",
        workout_type="bike_sweet_spot",
        status=status,
        is_active=True,
        planned_duration_min=60,
        intensity_target="Sweet Spot ~89% FTP",
        structured_workout=SWEET_SPOT_STRUCTURED,
        source="test",
    )


def _context(packet: dict[str, Any]) -> MorningContext:
    """What ``regenerate_for_verdict`` builds from a stored morning."""
    verdict = packet.get("verdict") or {}
    return MorningContext(
        status=verdict.get("status"),
        graded=stored_engine(packet) == ENGINE_GRADED,
        actions=stored_actions(packet),
        seen=stored_seen_workouts(packet),
        rest_day=stored_rest_day(packet),
    )


def _graded_packet(
    actions: dict[str, str], *, status: str = "Amber", seen: list[str] | None = None
) -> dict[str, Any]:
    return {
        "restDay": {"isRestDay": False},
        "plannedWorkouts": [{"id": workout_id} for workout_id in (seen or list(actions))],
        "verdict": {
            "engine": "graded",
            "status": status,
            "graded": {
                "actions": [
                    {"plannedWorkoutId": workout_id, "action": action}
                    for workout_id, action in actions.items()
                ]
            },
        },
    }


# -- 299.2: the weekly mix reads the graded actions ----------------------------------------


@pytest.mark.parametrize(
    ("status", "action"),
    [("Amber", "hold_targets"), ("Green", "move_or_hold")],
)
def test_a_session_that_stands_adds_no_shortfall(status: str, action: str) -> None:
    """W12's Sweet Spot held on an Amber (the light week), or held on a mild Green."""

    mix = _mix(status, {SWEET_SPOT_ID: action})

    assert mix.shortfall is None
    assert mix.eased is None
    assert mix.plan_adjustments() == []
    sweet_spot = mix.bucket(MIX_SWEET_SPOT)
    assert sweet_spot is not None and sweet_spot.at_risk is False
    assert "eased" not in mix.to_packet()


def test_a_light_week_amber_was_a_session_short_under_the_colour() -> None:
    """The same W12 morning read by the colour alone: the line this batch removes."""

    mix = _mix("Amber", None)

    assert mix.shortfall is not None
    assert mix.shortfall.message.startswith("No Sweet Spot session this week")


def test_an_eased_session_is_eased_not_lost() -> None:
    mix = _mix("Amber", {SWEET_SPOT_ID: "ease_hard"})

    assert mix.shortfall is None
    assert mix.eased is not None
    assert mix.eased.message == EASED_LINE
    assert mix.plan_adjustments() == [EASED_LINE]
    assert mix.to_packet()["eased"] == {
        "bucket": MIX_SWEET_SPOT,
        "label": "Sweet Spot",
        "message": EASED_LINE,
    }
    # Still in the week: today's session counts as scheduled, so the bucket is not short.
    sweet_spot = mix.bucket(MIX_SWEET_SPOT)
    assert sweet_spot is not None
    assert (sweet_spot.remaining_planned, sweet_spot.at_risk) == (1, False)


def test_a_graded_red_with_vo2_keeps_todays_shortfall() -> None:
    sessions = _w12(today_type="bike_vo2", today_id=VO2_ID)
    mix = _mix("Red", {VO2_ID: "recovery"}, sessions=sessions)

    assert mix.eased is None
    assert mix.shortfall is not None
    assert mix.shortfall.bucket == MIX_VO2
    assert mix.shortfall.message.startswith("No VO2 session this week")
    vo2 = mix.bucket(MIX_VO2)
    assert vo2 is not None and vo2.at_risk is True


@pytest.mark.parametrize("action", sorted(DROPPING_ACTIONS))
def test_every_dropping_action_keeps_the_shortfall(action: str) -> None:
    """A Red recovery spin, a shortened ride, and the floors' days off are unchanged."""

    mix = _mix("Red", {SWEET_SPOT_ID: action})

    assert mix.shortfall is not None and mix.shortfall.bucket == MIX_SWEET_SPOT
    assert mix.eased is None


def test_a_session_without_an_action_is_not_counted_as_dropped() -> None:
    """A skipped session, or one added after the morning, has no graded action."""

    mix = _mix("Amber", {})

    assert mix.shortfall is None and mix.eased is None


def test_the_ladder_reads_as_before() -> None:
    mix = _mix("Amber", None)
    packet = mix.to_packet()

    assert mix.shortfall is not None and mix.eased is None
    assert set(packet) == {"weekStart", "subjectDate", "buckets", "shortfall"}
    assert _mix("Green", None).shortfall is None


def test_a_rest_day_still_suppresses_both_lines() -> None:
    mix = _mix("Amber", {SWEET_SPOT_ID: "ease_hard"}, suppress_today_easing=True)

    assert mix.shortfall is None and mix.eased is None


# -- 299.3: the delivery rail offers nothing the morning did not decide --------------------


def test_1_oct_rest_day_amber_proposes_no_ride() -> None:
    context = _context(ONE_OCT_PACKET)
    paused = _ride(ONE_OCT_SWEET_SPOT_ID, status="skipped", day=date(2026, 10, 1))

    assert context.rest_day is True and context.graded is True
    # What the rail did on 1 Oct: no action, so the colour.
    assert context.transform_for(paused) == "Amber"
    assert context.proposal_for(paused) is None
    # Nor would a session the holiday had not paused get one on a rest day.
    assert context.proposal_for(_ride(day=date(2026, 10, 1))) is None


@pytest.mark.parametrize("status", ["skipped", "completed"])
def test_a_skipped_or_completed_session_gets_no_proposal(status: str) -> None:
    context = _context(_graded_packet({SWEET_SPOT_ID: "ease_hard"}))

    assert context.proposal_for(_ride(SWEET_SPOT_ID, status=status)) is None
    assert context.proposal_for(_ride(SWEET_SPOT_ID)) == "Amber"


def test_a_ride_the_graded_packet_saw_never_takes_the_colour() -> None:
    context = _context(_graded_packet({}, seen=[SWEET_SPOT_ID]))
    seen = _ride(SWEET_SPOT_ID)

    assert context.proposal_for(seen) is None
    # A ride the morning never saw (added after it) still takes the colour.
    assert context.proposal_for(_ride()) == "Amber"
    # Home's same-day send and push-on-plan-set keep the colour for a ride without an
    # action: there Mark has chosen to ride, and the colour is the cautious default.
    assert context.transform_for(seen) == "Amber"


def test_the_graded_actions_still_decide_a_live_ride() -> None:
    context = _context(
        _graded_packet({SWEET_SPOT_ID: "hold_targets", VO2_ID: "recovery"}, status="Red")
    )

    assert context.proposal_for(_ride(SWEET_SPOT_ID)) is None
    assert context.proposal_for(_ride(VO2_ID)) == "Red"


def test_the_ladder_rail_is_unchanged_on_a_training_day() -> None:
    ladder = {"restDay": {"isRestDay": False}, "verdict": {"status": "Amber"}}
    context = _context(ladder)

    assert context.graded is False
    assert context.proposal_for(_ride()) == "Amber"
    red = _context({"restDay": {"isRestDay": False}, "verdict": {"status": "Red"}})
    assert red.proposal_for(_ride()) == "Red"
    # The two guards hold under the ladder as well.
    assert context.proposal_for(_ride(status="skipped")) is None
    assert _context({**ladder, "restDay": {"isRestDay": True}}).proposal_for(_ride()) is None


def test_the_stored_morning_readers() -> None:
    assert stored_rest_day(ONE_OCT_PACKET) is True
    assert stored_rest_day({"verdict": {"isRestDay": True}}) is True
    assert stored_rest_day({"restDay": {"isRestDay": False}, "verdict": {"isRestDay": True}}) is (
        False
    )
    assert stored_rest_day({}) is False
    assert stored_rest_day(None) is False
    assert stored_seen_workouts(ONE_OCT_PACKET) == frozenset({ONE_OCT_SWEET_SPOT_ID})
    assert stored_seen_workouts({"plannedWorkouts": "not a list"}) == frozenset()
    assert stored_seen_workouts(None) == frozenset()


# -- 299.4: the graded prompt reads the eased line ------------------------------------------


def test_the_graded_prompt_reads_eased_and_dropped_and_the_ladder_keeps_its_sentence() -> None:
    ladder_sentence = (
        "When verdict.weeklyMix.shortfall is present, today's hard session is being eased:"
    )

    assert GRADED_PROMPT_VERSION == "morning-analysis-v58-2026-10-06"
    assert ladder_sentence in LADDER_SYSTEM_PROMPT
    assert "weeklyMix.eased" not in LADDER_SYSTEM_PROMPT
    assert ladder_sentence not in GRADED_SYSTEM_PROMPT
    flat = " ".join(GRADED_SYSTEM_PROMPT.split())
    assert (
        "When verdict.weeklyMix.eased is present, today's hard session still counts toward "
        "the week's mix: eased a zone at full length, or moved if he takes "
        "verdict.swapSuggestion. Say it is not lost, and never call the week a session short."
    ) in flat
    assert (
        "When verdict.weeklyMix.shortfall is present, today's hard session is dropped (a "
        "recovery spin, a shortened ride or a day off the bike): if shortfall.repatched is true"
    ) in flat


# -- PostgreSQL: the real reads (CI) ---------------------------------------------------------


@pytest.mark.asyncio
async def test_the_service_reads_each_sessions_id_for_its_action(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    player = _profile()
    async with session_factory() as session:
        session.add(player)
        await session.flush()
        sweet_spot = _planned(player.id, THU, "bike_sweet_spot", status="planned")
        session.add_all(
            [
                _planned(player.id, WED, "bike_endurance", status="completed"),
                sweet_spot,
                _planned(player.id, SAT, "bike_endurance", status="planned"),
            ]
        )
        await session.commit()
        service = WeeklyMixService(session)

        held = await service.summarize_for_verdict(
            player,
            THU,
            verdict_status="Amber",
            swap=None,
            session_actions={str(sweet_spot.id): "hold_targets"},
        )
        eased = await service.summarize_for_verdict(
            player,
            THU,
            verdict_status="Amber",
            swap=None,
            session_actions={str(sweet_spot.id): "ease_hard"},
        )
        ladder = await service.summarize_for_verdict(player, THU, verdict_status="Amber", swap=None)

    assert held.shortfall is None and held.eased is None
    assert eased.shortfall is None and eased.eased is not None
    assert eased.eased.message == EASED_LINE
    assert ladder.shortfall is not None


@pytest.mark.asyncio
async def test_regenerate_for_verdict_offers_nothing_on_a_rest_day_or_a_skipped_session(
    db_conn: AsyncConnection,
) -> None:
    """1 Oct 2026, reproduced: a holiday morning, graded Amber, and a paused Sweet Spot."""

    user_id = uuid.uuid4()
    subject = date(2026, 10, 1)
    await _seed_profile(db_conn, user_id)
    paused_id = uuid.UUID(ONE_OCT_SWEET_SPOT_ID)
    live_id = uuid.uuid4()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add_all(
            [
                PlannedWorkout(
                    id=paused_id,
                    user_id=user_id,
                    workout_date=subject,
                    version=2,
                    title="Sweet Spot (3 × 18 min @ 89%)",
                    workout_type="bike_sweet_spot",
                    status="skipped",
                    is_active=True,
                    planned_duration_min=88,
                    intensity_target="Sweet Spot ~89% FTP",
                    structured_workout=SWEET_SPOT_STRUCTURED,
                    source="holiday_pause",
                ),
                PlannedWorkout(
                    id=live_id,
                    user_id=user_id,
                    workout_date=subject,
                    version=1,
                    title="Sweet Spot (1 × 30 min @ 89%)",
                    workout_type="bike_sweet_spot",
                    status="planned",
                    is_active=True,
                    planned_duration_min=60,
                    intensity_target="Sweet Spot ~89% FTP",
                    structured_workout=SWEET_SPOT_STRUCTURED,
                    source="test",
                ),
            ]
        )
        await session.commit()

    def morning(packet: dict[str, Any]) -> Analysis:
        return Analysis(
            user_id=user_id,
            analysis_type="morning",
            subject_date=subject,
            generated_at_utc=datetime(2026, 10, 1, 8, 10),
            prompt_version="morning-analysis-test",
            verdict="Amber",
            context_packet=packet,
            output_markdown="Amber verdict",
            raw_response={},
        )

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session)

        rest_day = await service.regenerate_for_verdict(
            user, subject, analysis=morning(ONE_OCT_PACKET)
        )
        assert rest_day == []
        assert (await session.execute(select(WorkoutDeliveryProposal))).scalars().all() == []

        # A training morning that eases both: only the live session is offered.
        training = _graded_packet({ONE_OCT_SWEET_SPOT_ID: "ease_hard", str(live_id): "ease_hard"})
        offered = await service.regenerate_for_verdict(user, subject, analysis=morning(training))
        assert [proposal.planned_workout_id for proposal in offered] == [live_id]
