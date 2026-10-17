"""Batch 344: compare completed rides by the workout Garmin recorded."""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import Activity
from src.models.profile import Profile, UserRole
from src.services.brief_chat import _prompt_history_turn, _strip_history_labels
from src.services.chat_context import ChatContextService
from src.services.coach_ride_history import RideSample, previous_ride
from src.services.coach_sections import activity_state
from src.services.coach_tools import CoachToolbox


def _ride(
    day: int, title: str, minutes: float, *, month: int = 9, kind: str = "indoor_cycling"
) -> RideSample:
    return RideSample(
        id=uuid4(),
        activity_name=title,
        activity_type=kind,
        start_utc=datetime(2026, month, day, 9),
        duration_sec=minutes * 60,
        avg_heart_rate_bpm=120,
        max_heart_rate_bpm=128,
        avg_power_watts=179,
        normalized_power_watts=180,
    )


def test_10_oct_long_z2_finds_same_ride_not_8_oct_easy_z2() -> None:
    current = _ride(10, "2nd 2121 Wk 12 WO 5 Long Z2", 85, month=10)
    easy = _ride(8, "2nd 2121 Wk 12 WO 2 Easy Z2", 45, month=10)
    earlier = _ride(19, "2nd 2121 Wk 9 WO 5 Long Z2", 90)
    assert previous_ride(current, [easy, earlier]) == earlier


def test_generic_indoor_cycling_uses_type_and_near_duration() -> None:
    current = _ride(23, "Indoor Cycling", 53)
    wrong_type = _ride(22, "Indoor Cycling", 53, kind="road_biking")
    too_short = _ride(21, "Indoor Cycling", 45)
    earlier = _ride(20, "Indoor Cycling", 58)
    assert previous_ride(current, [wrong_type, too_short, earlier]) == earlier
    assert previous_ride(current, [_ride(22, "Sweet Spot", 53)]) is None


def test_generic_duration_matches_the_minutes_shown_to_mark() -> None:
    current = _ride(23, "Indoor Cycling", 3150.37109375 / 60)
    earlier = _ride(22, "Indoor Cycling", 3480.493896484375 / 60)
    assert previous_ride(current, [earlier]) == earlier


def test_adjusted_prefix_does_not_change_workout_identity() -> None:
    current = _ride(10, "2nd 2121 Wk 12 WO 4 Amber-adjusted: Z2 + Neuromuscular", 44, month=10)
    earlier = _ride(19, "2nd 2121 Wk 8 WO 4 Z2 + Neuromuscular", 58)
    assert previous_ride(current, [earlier]) == earlier


def test_activity_shape_carries_peak_heart_rate() -> None:
    row = SimpleNamespace(
        id=uuid4(),
        start_utc=datetime(2026, 10, 10, 9),
        activity_name="Long Z2",
        activity_type="indoor_cycling",
        duration_sec=5100,
        distance_m=None,
        avg_heart_rate_bpm=120,
        max_heart_rate_bpm=128,
        avg_power_watts=179,
        normalized_power_watts=180,
        training_load=None,
        aerobic_training_effect=None,
    )
    assert activity_state(row, lambda moment: moment.date())["maxHeartRateBpm"] == 128


def test_history_turn_has_local_day_time_and_origin_but_storage_is_untouched() -> None:
    row = SimpleNamespace(
        role="user",
        content="That was 115 yesterday.",
        created_utc=datetime(2026, 10, 8, 13, 16),
        origin_kind="home",
        origin_date=None,
    )
    rendered = _prompt_history_turn(row, "Europe/London", datetime(2026, 10, 10, 14))
    assert rendered["role"] == "user"
    assert "8 Oct 2026" in rendered["content"]
    assert "14:16" in rendered["content"]
    assert "home screen" in rendered["content"]
    assert rendered["content"].endswith(row.content)
    assert row.content == "That was 115 yesterday."
    today = SimpleNamespace(**{**vars(row), "created_utc": datetime(2026, 10, 10, 13, 53)})
    today_prompt = _prompt_history_turn(today, "Europe/London", datetime(2026, 10, 10, 14))
    assert "Today" in today_prompt["content"]


def test_history_label_is_removed_if_model_echoes_it() -> None:
    answer = "[[TURN_CONTEXT: 8 Oct 2026, 14:16; from his home screen]]\nThe ride was 85 minutes."
    assert _strip_history_labels(answer) == "The ride was 85 minutes."


def test_today_uses_local_day_across_utc_midnight() -> None:
    row = SimpleNamespace(
        role="user",
        content="A late question.",
        created_utc=datetime(2026, 10, 9, 23, 30),
        origin_kind="general",
        origin_date=None,
    )
    rendered = _prompt_history_turn(row, "Europe/London", datetime(2026, 10, 10, 0, 10))
    assert "Today 10 Oct 2026, 00:30" in rendered["content"]


@pytest.mark.asyncio
async def test_live_context_and_lookup_carry_the_previous_ride(db_conn: AsyncConnection) -> None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = Profile(
            id=uuid4(),
            display_name="Ride comparison",
            role=UserRole.player,
            timezone="Europe/London",
            is_active=True,
        )
        other = Profile(
            id=uuid4(),
            display_name="Other ride",
            role=UserRole.player,
            timezone="Europe/London",
            is_active=True,
        )
        session.add_all([player, other])
        await session.flush()

        def add_ride(
            user_id: object,
            garmin_id: int,
            title: str,
            when: datetime,
            avg_hr: int,
            max_hr: int,
        ) -> None:
            session.add(
                Activity(
                    id=uuid4(),
                    user_id=user_id,
                    garmin_activity_id=garmin_id,
                    activity_name=title,
                    activity_type="indoor_cycling",
                    start_utc=when,
                    created_at=when + timedelta(hours=2),
                    duration_sec=5100 if when.month == 10 else 5400,
                    avg_heart_rate_bpm=avg_hr,
                    max_heart_rate_bpm=max_hr,
                    avg_power_watts=179,
                    normalized_power_watts=180,
                    raw_summary={},
                )
            )

        add_ride(
            player.id, 344001, "2nd 2121 Wk 9 WO 5 Long Z2", datetime(2026, 9, 19, 9), 111, 118
        )
        add_ride(
            player.id, 344002, "2nd 2121 Wk 12 WO 2 Easy Z2", datetime(2026, 10, 8, 9), 115, 128
        )
        add_ride(
            player.id, 344003, "2nd 2121 Wk 12 WO 5 Long Z2", datetime(2026, 10, 10, 9), 120, 128
        )
        add_ride(
            other.id, 344004, "2nd 2121 Wk 10 WO 5 Long Z2", datetime(2026, 10, 9, 9), 199, 200
        )
        await session.commit()

        live = await ChatContextService(session)._recent_activities(
            player.id,
            datetime(2026, 10, 10).date(),
            player.timezone,
            asked_at_utc=datetime(2026, 10, 10, 12),
        )
        tool = await CoachToolbox(session, player).activities(
            {
                "startDate": "2026-10-10",
                "endDate": "2026-10-10",
            }
        )

    current = next(row for row in live if row["localDate"] == "2026-10-10")
    assert current["maxHeartRateBpm"] == 128
    assert current["previousSameWorkout"]["localDate"] == "2026-09-19"
    assert current["previousSameWorkout"]["maxHeartRateBpm"] == 118
    assert current["previousSameWorkout"]["avgHeartRateBpm"] == 111
    assert current["previousSameWorkout"]["matchBasis"] == "workout_name"
    fetched = json.loads(tool)
    assert fetched["rows"][0]["previousSameWorkout"] == current["previousSameWorkout"]
