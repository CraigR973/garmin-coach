"""Batch 343: a day with no plan, and the small screen fixes.

343.1 a day no plan block covers is "No plan loaded" in today's call, on Home and on Week,
never planned rest (UX333-06). The rest of 343.2 is web-only and tested there
(``SettingsPage.test.tsx``, ``DashboardPage.test.tsx``, ``WeekAheadPage.test.tsx``).
Each failed on ``main`` first.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from src.models.coaching import PlanBlock
from src.models.profile import Profile, UserRole
from src.services.daily_loop_envelope import _in_plan_week
from src.services.plan_actions import NO_PLAN_DAY_LABEL, PlanActionService
from src.services.todays_call import (
    NO_SESSION_PLANNED,
    NO_SESSION_PLANNED_LINE,
    STATE_NO_SESSION_PLANNED,
    todays_call,
)
from tests.test_batch_302_stored_morning import _savepoint_session

REPO = Path(__file__).resolve().parents[3]
DRAFT = REPO / "docs" / "drafts" / "2026-10-29-batch-343-wording.md"


def test_a_day_outside_every_plan_says_no_plan_is_loaded() -> None:
    call = todays_call(
        {
            "plannedWorkouts": [],
            "restDay": {"isRestDay": False, "insidePlanWeek": False},
            "verdict": {"status": "Green", "engine": "graded", "acutePhysiology": {}},
        }
    )
    assert (call.state, call.headline, call.line) == (
        STATE_NO_SESSION_PLANNED,
        NO_SESSION_PLANNED,
        NO_SESSION_PLANNED_LINE,
    )
    assert call.headline == "No plan loaded"
    assert "rest" not in call.line.lower()


def test_every_new_line_is_in_the_draft() -> None:
    draft = DRAFT.read_text(encoding="utf-8")
    for words in (NO_SESSION_PLANNED, NO_SESSION_PLANNED_LINE, NO_PLAN_DAY_LABEL):
        assert words in draft, words


@pytest.mark.asyncio
async def test_on_postgres_week_and_home_know_which_days_a_plan_covers(
    db_conn: AsyncConnection,
) -> None:
    start = date(2026, 8, 10)
    async with _savepoint_session(db_conn) as session:
        player = Profile(
            id=uuid.uuid4(),
            display_name="No Plan",
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()
        session.add(
            PlanBlock(
                user_id=player.id,
                name="Plan No. 3",
                start_date=start,
                end_date=start + timedelta(days=2),
                goals_json={},
                raw_plan={},
            )
        )
        await session.commit()

        schedule = await PlanActionService(session).schedule(player, start_date=start, days=5)

        covered = [day.in_plan for day in schedule.days]
        assert covered == [True, True, True, False, False]
        labels = [day.day_state.label for day in schedule.days]
        assert labels == ["Rest", "Rest", "Rest", NO_PLAN_DAY_LABEL, NO_PLAN_DAY_LABEL]
        assert await _in_plan_week(session, player.id, start) is True
        assert await _in_plan_week(session, player.id, start + timedelta(days=4)) is False
