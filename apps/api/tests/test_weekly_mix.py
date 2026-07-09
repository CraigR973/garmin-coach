"""Tests for Batch 70 weekly-mix maintenance & dynamic rebalancing (#143).

Covers the acceptance pillars: deterministic done/due/at-risk accounting derived
from the plan's own mix; a readiness-dropped hard session re-patched when spacing
allows and an explicit "not this week" otherwise; Mon/Fri protection; nothing
mutated or scheduled.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from src.models.coaching import PlannedWorkout
from src.models.profile import Profile, UserRole
from src.services.weekly_mix import (
    MIX_SWEET_SPOT,
    MIX_VO2,
    MIX_Z2,
    MixSession,
    WeeklyMixService,
    _eased_bucket,
    build_shortfall,
    mix_bucket,
    summarize_weekly_mix,
)
from src.services.weekly_restructure import SwapSuggestion

# Week of Monday 2026-06-22 — the real plan shape: VO2 Tue, SS Wed, Z2 Thu/Sat/Sun.
MON = date(2026, 6, 22)
TUE = date(2026, 6, 23)
WED = date(2026, 6, 24)
THU = date(2026, 6, 25)
FRI = date(2026, 6, 26)
SAT = date(2026, 6, 27)
SUN = date(2026, 6, 28)


def _session(workout_date: date, workout_type: str, *, completed: bool = False) -> MixSession:
    return MixSession(workout_date=workout_date, workout_type=workout_type, completed=completed)


def _plan_week(*, completed: set[date] | None = None) -> list[MixSession]:
    """The plan's intended mix (VO2×1 / SS×1 / Z2×3), with ``completed`` dates flipped."""
    done = completed or set()
    return [
        _session(TUE, "bike_vo2", completed=TUE in done),
        _session(WED, "bike_sweet_spot", completed=WED in done),
        _session(THU, "bike_endurance", completed=THU in done),
        _session(SAT, "bike_endurance", completed=SAT in done),
        _session(SUN, "bike_endurance", completed=SUN in done),
    ]


# ---------------------------------------------------------------------------
# Bucket mapping
# ---------------------------------------------------------------------------


def test_mix_bucket_maps_bike_types_and_ignores_non_bike() -> None:
    assert mix_bucket("bike_vo2") == MIX_VO2
    assert mix_bucket("bike_sweet_spot") == MIX_SWEET_SPOT
    assert mix_bucket("bike_threshold") == MIX_SWEET_SPOT
    assert mix_bucket("bike_endurance") == MIX_Z2
    assert mix_bucket("bike_recovery") == MIX_Z2
    assert mix_bucket("bike_tempo") == MIX_Z2
    assert mix_bucket("strength_maintenance") is None
    assert mix_bucket("mobility") is None


# ---------------------------------------------------------------------------
# 70.1 — deterministic accounting
# ---------------------------------------------------------------------------


def test_full_week_nothing_done_is_on_track() -> None:
    mix = summarize_weekly_mix(_plan_week(), subject_date=MON)
    assert mix.week_start == MON
    vo2 = mix.bucket(MIX_VO2)
    assert vo2 is not None
    assert (vo2.target, vo2.done, vo2.due, vo2.remaining_planned, vo2.at_risk) == (
        1,
        0,
        1,
        1,
        False,
    )
    z2 = mix.bucket(MIX_Z2)
    assert z2 is not None
    assert (z2.target, z2.done, z2.due, z2.remaining_planned, z2.at_risk) == (3, 0, 3, 3, False)
    assert mix.at_risk_buckets == []
    assert mix.shortfall is None


def test_target_is_derived_from_the_week_not_hardcoded() -> None:
    # A recovery week with no VO2 must read target 0, never a phantom shortfall.
    recovery_week = [
        _session(TUE, "bike_endurance"),
        _session(THU, "bike_recovery"),
        _session(SAT, "bike_endurance"),
    ]
    mix = summarize_weekly_mix(recovery_week, subject_date=MON)
    vo2 = mix.bucket(MIX_VO2)
    assert vo2 is not None
    assert vo2.target == 0 and vo2.due == 0 and vo2.at_risk is False
    z2 = mix.bucket(MIX_Z2)
    assert z2 is not None
    assert z2.target == 3


def test_completed_counts_as_done_and_past_uncompleted_is_a_miss() -> None:
    # As of Friday: Tue VO2 done, Thu Z2 done; Wed SS was never done (a miss).
    mix = summarize_weekly_mix(_plan_week(completed={TUE, THU}), subject_date=FRI)
    vo2 = mix.bucket(MIX_VO2)
    assert vo2 is not None
    assert vo2.done == 1 and vo2.due == 0 and vo2.at_risk is False
    ss = mix.bucket(MIX_SWEET_SPOT)
    assert ss is not None
    # Wednesday's SS is past and uncompleted → a miss, not a future slot.
    assert ss.done == 0 and ss.due == 1 and ss.remaining_planned == 0 and ss.at_risk is True
    z2 = mix.bucket(MIX_Z2)
    assert z2 is not None
    # Thu done; Sat+Sun still ahead → due 2, two slots left, on track.
    assert z2.done == 1 and z2.due == 2 and z2.remaining_planned == 2 and z2.at_risk is False


def test_easing_todays_hard_session_reads_that_bucket_at_risk() -> None:
    mix = summarize_weekly_mix(_plan_week(), subject_date=TUE, eased_bucket=MIX_VO2)
    vo2 = mix.bucket(MIX_VO2)
    assert vo2 is not None
    # Today's VO2 is dropped, so it is no longer a scheduled hard slot.
    assert vo2.target == 1 and vo2.done == 0 and vo2.remaining_planned == 0 and vo2.at_risk is True
    # The still-upcoming Sweet-Spot (Wed) is untouched.
    ss = mix.bucket(MIX_SWEET_SPOT)
    assert ss is not None
    assert ss.at_risk is False
    assert [b.bucket for b in mix.at_risk_buckets] == [MIX_VO2]


# ---------------------------------------------------------------------------
# eased-bucket detection
# ---------------------------------------------------------------------------


def test_eased_bucket_only_on_cautious_morning_with_uncompleted_hard_today() -> None:
    today_vo2 = [_session(TUE, "bike_vo2")]
    assert _eased_bucket(today_vo2, subject_date=TUE, verdict_status="Amber") == MIX_VO2
    assert _eased_bucket(today_vo2, subject_date=TUE, verdict_status="Red") == MIX_VO2
    assert _eased_bucket(today_vo2, subject_date=TUE, verdict_status="Green") is None

    already_done = [_session(TUE, "bike_vo2", completed=True)]
    assert _eased_bucket(already_done, subject_date=TUE, verdict_status="Amber") is None

    easy_today = [_session(TUE, "bike_endurance")]
    assert _eased_bucket(easy_today, subject_date=TUE, verdict_status="Amber") is None


# ---------------------------------------------------------------------------
# 70.2 — shortfall message (re-patch vs not-this-week)
# ---------------------------------------------------------------------------


def test_build_shortfall_repatched_names_the_day() -> None:
    swap = SwapSuggestion(
        subject_date=TUE,
        hard_workout_id=uuid.uuid4(),
        hard_title="VO2 30/15",
        hard_category="vo2",
        move_to_date=SAT,
        bring_forward_workout_id=uuid.uuid4(),
        bring_forward_title="Saturday Z2",
    )
    shortfall = build_shortfall(eased_bucket=MIX_VO2, swap=swap)
    assert shortfall.repatched is True
    assert shortfall.move_to_weekday == "Saturday"
    assert shortfall.move_to_date == SAT
    assert "Saturday" in shortfall.message
    assert "VO2" in shortfall.message


def test_build_shortfall_not_this_week_when_no_swap() -> None:
    shortfall = build_shortfall(eased_bucket=MIX_VO2, swap=None)
    assert shortfall.repatched is False
    assert shortfall.move_to_weekday is None
    assert shortfall.move_to_date is None
    assert "No VO2 session this week" in shortfall.message
    assert "readiness" in shortfall.message.lower()


# ---------------------------------------------------------------------------
# 70.2/70.3 — service over real rows (DB-backed)
# ---------------------------------------------------------------------------


def _profile() -> Profile:
    return Profile(
        id=uuid.uuid4(),
        display_name="Mix Test",
        pin_hash="x" * 60,
        role=UserRole.admin,
        timezone="Europe/London",
        latitude=55.6045,
        longitude=-4.5249,
        is_active=True,
    )


def _planned(
    user_id: uuid.UUID, workout_date: date, workout_type: str, *, status: str
) -> PlannedWorkout:
    return PlannedWorkout(
        user_id=user_id,
        workout_date=workout_date,
        version=1,
        title=workout_type,
        workout_type=workout_type,
        status=status,
        is_active=True,
        planned_duration_min=60,
        intensity_target="test",
        structured_workout={"format": "bike"},
        source="test",
    )


@pytest.mark.asyncio
async def test_service_repatches_dropped_vo2_when_a_later_easy_day_exists(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    player = _profile()
    async with session_factory() as session:
        session.add(player)
        await session.flush()
        session.add_all(
            [
                _planned(player.id, TUE, "bike_vo2", status="planned"),
                _planned(player.id, WED, "bike_sweet_spot", status="planned"),
                _planned(player.id, SAT, "bike_endurance", status="planned"),
            ]
        )
        await session.commit()

        mix = await WeeklyMixService(session).summarize_for_verdict(
            player, TUE, verdict_status="Amber", swap=None
        )

    assert mix.shortfall is not None
    assert mix.shortfall.bucket == MIX_VO2
    assert mix.shortfall.repatched is True
    assert mix.shortfall.move_to_date == SAT
    # The raw accounting still reflects the current (un-swapped) plan: at risk.
    vo2 = mix.bucket(MIX_VO2)
    assert vo2 is not None and vo2.at_risk is True
    # Message flows through to the verdict's plan adjustments.
    assert any("Saturday" in line for line in mix.plan_adjustments())


@pytest.mark.asyncio
async def test_service_says_not_this_week_when_no_sound_later_slot(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    player = _profile()
    async with session_factory() as session:
        session.add(player)
        await session.flush()
        # VO2 today, and the only later bike day is a protected Friday — no sound slot.
        session.add_all(
            [
                _planned(player.id, TUE, "bike_vo2", status="planned"),
                _planned(player.id, FRI, "bike_endurance", status="planned"),
            ]
        )
        await session.commit()

        mix = await WeeklyMixService(session).summarize_for_verdict(
            player, TUE, verdict_status="Red", swap=None
        )

    assert mix.shortfall is not None
    assert mix.shortfall.repatched is False
    assert "No VO2 session this week" in mix.shortfall.message


@pytest.mark.asyncio
async def test_service_green_morning_reports_mix_without_a_shortfall(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    player = _profile()
    async with session_factory() as session:
        session.add(player)
        await session.flush()
        session.add_all(
            [
                _planned(player.id, TUE, "bike_vo2", status="completed"),
                _planned(player.id, WED, "bike_sweet_spot", status="planned"),
                _planned(player.id, THU, "bike_endurance", status="planned"),
            ]
        )
        await session.commit()

        mix = await WeeklyMixService(session).summarize_for_verdict(
            player, THU, verdict_status="Green", swap=None
        )

    assert mix.shortfall is None
    vo2 = mix.bucket(MIX_VO2)
    assert vo2 is not None and vo2.done == 1 and vo2.due == 0
    assert mix.plan_adjustments() == []
