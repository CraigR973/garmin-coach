"""Batch 321: three small fixes.

321.1 the swap withheld on an off-the-bike day has a test (removing the rule failed none);
321.2 a reading missing inside a row that arrived says so rather than passing for normal;
321.3 a head cold, a missing-data morning and a Red strength day each read what the engine
knows. Each failed on ``main`` first.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from src.models.coaching import (
    DAILY_METRIC_PHASE_MORNING,
    Analysis,
    DailyMetric,
    ManualEntry,
    PlannedWorkout,
    Sleep,
)
from src.models.profile import Profile, UserRole
from src.services import morning_analysis
from src.services.morning_analysis import MorningAnalysisService
from src.services.morning_verdict import RED_STRENGTH_PLAN_LINE, _red_plan_lines
from src.services.todays_call import (
    HEAD_COLD,
    HEAD_COLD_LINE,
    NOT_ENOUGH_DATA,
    NOT_ENOUGH_DATA_EASY_LINE,
    NOT_ENOUGH_DATA_HARD_LINE,
    READING_NOT_ENOUGH_DATA,
    STATE_HEAD_COLD,
    STATE_NOT_ENOUGH_DATA,
    todays_call,
)
from src.services.verdict_grading import (
    MISSING_HRV_REASON,
    MISSING_SLEEP_SCORE_REASON,
    grade,
)
from tests.test_batch_295_verdict_grading import _inputs

REPO = Path(__file__).resolve().parents[3]
DRAFT = REPO / "docs" / "drafts" / "2026-10-29-batch-321-wording.md"


# -- 321.1: no ride offered on a day off the bike ------------------------------------------------


async def _seed_bike_rest_cluster(session: Any, subject_date: date) -> Profile:
    """An illness-grade HRV drop today, two unexplained Reds this week, VO2 today and an
    easy ride in three days: the cluster offers a swap, and the rail rests the bike."""
    user_id = uuid.uuid4()
    player = Profile(
        id=user_id,
        display_name="Bike Rest Swap",
        role=UserRole.admin,
        timezone="Europe/London",
        is_active=True,
    )
    session.add(player)
    await session.flush()
    for offset in range(31):
        day = subject_date - timedelta(days=30 - offset)
        session.add(
            Sleep(
                user_id=user_id,
                calendar_date=day,
                score=85,
                duration_sec=7 * 3600,
                raw_payload={},
                factors_json={},
            )
        )
        session.add(
            DailyMetric(
                user_id=user_id,
                calendar_date=day,
                phase=DAILY_METRIC_PHASE_MORNING,
                recorded_at_utc=datetime.combine(day, datetime.min.time()),
                readiness_score=75,
                readiness_level="High",
                hrv_last_night_avg_ms=20 if day == subject_date else (47, 48, 49)[offset % 3],
                hrv_weekly_avg_ms=48,
                hrv_status="Balanced",
                resting_heart_rate_bpm=45,
                raw_payload={},
            )
        )
    for day in (subject_date - timedelta(days=6), subject_date - timedelta(days=1)):
        session.add(
            Analysis(
                user_id=user_id,
                analysis_type="morning",
                subject_date=day,
                generated_at_utc=datetime.combine(day, datetime.min.time()),
                prompt_version="historical-test",
                verdict="Red",
                context_packet={"verdict": {"status": "Red"}},
                output_markdown="Red.",
                raw_response={},
            )
        )
    session.add_all(
        [
            ManualEntry(
                user_id=user_id,
                entry_date=subject_date,
                entry_at_utc=datetime.combine(subject_date, datetime.min.time())
                + timedelta(hours=6),
                subjective_score=7,
            ),
            PlannedWorkout(
                user_id=user_id,
                workout_date=subject_date,
                version=1,
                title="VO2 Max 30/30",
                workout_type="bike_vo2",
                status="planned",
                is_active=True,
                planned_duration_min=60,
                structured_workout={"format": "bike"},
                source="test",
            ),
            PlannedWorkout(
                user_id=user_id,
                workout_date=subject_date + timedelta(days=3),
                version=1,
                title="Endurance Z2",
                workout_type="bike_endurance",
                status="planned",
                is_active=True,
                planned_duration_min=75,
                structured_workout={"format": "bike"},
                source="test",
            ),
        ]
    )
    await session.commit()
    return player


@pytest.mark.asyncio
async def test_on_postgres_no_swap_is_offered_on_a_day_off_the_bike(
    db_conn: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 22 Sep defect (Batch 277): told to stay off the bike and handed a ride."""
    subject_date = date(2026, 8, 20)
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        player = await _seed_bike_rest_cluster(session, subject_date)
        packet = await MorningAnalysisService(session).assemble_context_packet(player, subject_date)
        verdict = packet["verdict"]
        assert verdict["acutePhysiology"]["requiresBikeRest"] is True
        assert verdict["chronicAction"]["kind"] == "rearrange_proposal"
        assert verdict.get("swapSuggestion") is None

        # The test holds the rule: without it the same morning offers the swap.
        monkeypatch.setattr(morning_analysis, "_requires_bike_rest", lambda _verdict: False)
        unguarded = await MorningAnalysisService(session).assemble_context_packet(
            player, subject_date
        )
        assert unguarded["verdict"].get("swapSuggestion") is not None


# -- 321.2: a missing reading says so ---------------------------------------------------------


def test_a_missing_hrv_reading_or_sleep_score_is_named_and_moves_nothing() -> None:
    base = _inputs()
    acute = {**base.acute, "overnightHrv": {**base.acute["overnightHrv"], "currentMs": None}}
    no_hrv = grade(replace(base, acute=acute))
    assert MISSING_HRV_REASON in no_hrv.reasons
    assert no_hrv.status == grade(base).status
    no_score = grade(replace(base, sleep_score_age_adjusted=None, sleep_score_raw=None))
    assert MISSING_SLEEP_SCORE_REASON in no_score.reasons
    assert MISSING_HRV_REASON not in grade(base).reasons


# -- 321.3: calls that say what the engine knows ---------------------------------------------


def _packet(status: str, actions: list[dict[str, Any]], **graded: Any) -> dict[str, Any]:
    return {
        "plannedWorkouts": [{"id": "w"}],
        "restDay": {"isRestDay": False},
        "verdict": {
            "status": status,
            "engine": "graded",
            "acutePhysiology": graded.pop("acute", {}),
            "graded": {"actions": actions, **graded},
        },
    }


def test_a_head_cold_reads_as_a_cold_not_still_recovering() -> None:
    call = todays_call(
        _packet(
            "Red",
            [{"action": "recovery", "workoutType": "bike_vo2", "isHard": True}],
            acute={"symptoms": {"floor": "easy_riding_only", "triggered": True}},
        )
    )
    assert (call.state, call.headline, call.line) == (STATE_HEAD_COLD, HEAD_COLD, HEAD_COLD_LINE)


def test_a_missing_data_amber_is_not_fatigue() -> None:
    hard = todays_call(
        _packet(
            "Amber",
            [{"action": "ease_hard", "workoutType": "bike_vo2", "isHard": True}],
            missingDataFloorApplied=True,
        )
    )
    assert (hard.state, hard.headline, hard.line, hard.reading) == (
        STATE_NOT_ENOUGH_DATA,
        NOT_ENOUGH_DATA,
        NOT_ENOUGH_DATA_HARD_LINE,
        READING_NOT_ENOUGH_DATA,
    )
    assert "fatigue" not in hard.line
    easy = todays_call(
        _packet(
            "Amber",
            [{"action": "as_planned", "workoutType": "bike_z2", "isHard": False}],
            missingDataFloorApplied=True,
        )
    )
    assert easy.line == NOT_ENOUGH_DATA_EASY_LINE
    # An Amber for a real reason keeps its words.
    real = todays_call(
        _packet("Amber", [{"action": "ease_hard", "workoutType": "bike_vo2", "isHard": True}])
    )
    assert real.state != STATE_NOT_ENOUGH_DATA


def test_a_red_strength_day_holds_the_weight_rather_than_substituting() -> None:
    strength = PlannedWorkout(
        id=uuid.uuid4(), workout_type="strength", status="planned", title="Dumbbells A"
    )
    assert _red_plan_lines([strength]) == [RED_STRENGTH_PLAN_LINE]
    ride = PlannedWorkout(id=uuid.uuid4(), workout_type="bike_vo2", status="planned", title="VO2")
    assert _red_plan_lines([strength, ride]) != [RED_STRENGTH_PLAN_LINE]


def test_every_new_line_is_in_the_draft() -> None:
    draft = DRAFT.read_text(encoding="utf-8")
    for words in (
        HEAD_COLD,
        HEAD_COLD_LINE,
        NOT_ENOUGH_DATA,
        NOT_ENOUGH_DATA_HARD_LINE,
        NOT_ENOUGH_DATA_EASY_LINE,
        RED_STRENGTH_PLAN_LINE,
        MISSING_HRV_REASON,
        MISSING_SLEEP_SCORE_REASON,
    ):
        assert words in draft, words
