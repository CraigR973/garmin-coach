"""The strength read must not need ``activities.raw_summary`` on the object it is handed.

The post-workout backstop loads its activities with ``raw_summary`` deferred and
``raiseload`` on (``without_activity_raw_summary``, Batch 340). Batch 368.1 then made the
strength matcher read the watch's exercise categories off that attribute, so a planned
Dumbbells A or B on the day made the backstop's strength reader raise
``InvalidRequestError: 'Activity.raw_summary' is not available due to raiseload=True``.
The job recorded ``degraded`` and that session's read was never written.

These tests drive the same call the backstop makes, over objects loaded the way it loads
them.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from src.models.coaching import Activity, Analysis, PlanBlock, PlannedWorkout
from src.models.profile import Profile, UserRole
from src.services.bulk_history_reads import without_activity_raw_summary
from src.services.post_strength_analysis import PostStrengthAnalysisService
from src.services.post_workout_analysis import ClaudeGenerationResult
from src.services.workout_categories import DAY_CATEGORY_CYCLE, DAY_CATEGORY_WALK
from src.services.workout_match import material_difference

SESSION_DAY = date(2026, 7, 2)  # well before today: a fresh profile seeds a plan from today
WATCH_A = ["DEADLIFT", "LUNGE", "ROW", "SQUAT"]
CIRCUIT = ["SQUAT", "PLANK"]


@dataclass
class _FakeClient:
    calls: int = 0

    async def generate(
        self, *, context_packet: dict[str, Any], user_prompt: str
    ) -> ClaudeGenerationResult:
        self.calls += 1
        return ClaudeGenerationResult(
            output_markdown="**Strength read:** a steady session.\n\n- Heart rate stayed low.",
            raw_response={"id": "msg_test", "content": [{"type": "text", "text": "ok"}]},
            model_name="claude-test",
        )


async def _seed(
    db_conn: AsyncConnection, *, categories: list[str], title: str = "Dumbbells A (legs and back)"
) -> tuple[Profile, uuid.UUID, uuid.UUID]:
    """A planned dumbbell session and a recorded one, committed. Returns (profile, plan, act)."""
    factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with factory() as session:
        player = Profile(
            id=uuid.uuid4(),
            display_name="Backstop Raw Summary Test",
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()
        block = PlanBlock(
            user_id=player.id,
            name="Backstop Block",
            version=1,
            sequence_index=1,
            block_type="build",
            start_date=date(2026, 6, 29),
            end_date=date(2026, 7, 5),
            goals_json={},
            raw_plan={},
        )
        session.add(block)
        await session.flush()
        planned = PlannedWorkout(
            user_id=player.id,
            plan_block_id=block.id,
            workout_date=SESSION_DAY,
            title=title,
            workout_type="strength_maintenance",
            version=1,
            is_active=True,
            structured_workout={"summary": "Dumbbells", "steps": []},
        )
        activity = Activity(
            user_id=player.id,
            garmin_activity_id=910001,
            activity_name="Dumbbell Workout",
            activity_type="strength_training",
            start_utc=datetime(2026, 7, 2, 7, 30),
            duration_sec=2400,
            avg_heart_rate_bpm=98,
            max_heart_rate_bpm=128,
            exclude_from_recovery=True,
            raw_summary={
                "activityType": {"typeKey": "strength_training"},
                "summarizedExerciseSets": [
                    {"category": item, "sets": 3, "reps": 10, "maxWeight": 8000.0}
                    for item in categories
                ],
            },
        )
        session.add_all([planned, activity])
        await session.commit()
        return player, planned.id, activity.id


@pytest.mark.asyncio
async def test_the_backstop_reads_a_dumbbell_session_against_its_planned_row(
    db_conn: AsyncConnection,
) -> None:
    """Planned Dumbbells A plus a recorded hinge and lunge: read, and the plan row completes."""
    player, planned_id, activity_id = await _seed(db_conn, categories=WATCH_A)
    factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    client = _FakeClient()

    # A fresh session, as the backstop has: nothing seeded is in its identity map.
    async with factory() as session:
        results = await PostStrengthAnalysisService(session).generate_for_pending_strength(
            player, since=datetime(2026, 7, 2), client=client, commit=False
        )

        assert [item.generated for item in results] == [True]
        assert client.calls == 1
        packet = results[0].analysis.context_packet
        assert packet["plannedMatch"] == {
            "materiallyDifferent": False,
            "plannedWorkoutId": str(planned_id),
        }
        assert packet["sessionLoad"]["exercises"], "what he lifted still reaches the packet"
        stored = await session.scalar(select(Analysis).where(Analysis.activity_id == activity_id))
        assert stored is not None
        planned = await session.get(PlannedWorkout, planned_id)
        assert planned is not None
        assert planned.status == "completed"


@pytest.mark.asyncio
async def test_the_backstop_still_reports_a_circuit_that_is_not_dumbbells_a(
    db_conn: AsyncConnection,
) -> None:
    """The mismatch rule still fires on the deferred object: read, plan row left alone."""
    player, planned_id, _ = await _seed(db_conn, categories=CIRCUIT)
    factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)

    async with factory() as session:
        results = await PostStrengthAnalysisService(session).generate_for_pending_strength(
            player, since=datetime(2026, 7, 2), client=_FakeClient(), commit=False
        )

        assert [item.generated for item in results] == [True]
        packet = results[0].analysis.context_packet
        assert packet["plannedMatch"]["materiallyDifferent"] is True
        assert packet["plannedMatch"]["kind"] == "exercise_mismatch"
        planned = await session.get(PlannedWorkout, planned_id)
        assert planned is not None
        assert planned.status != "completed"


@pytest.mark.asyncio
async def test_no_category_rule_needs_the_summary_on_a_deferred_activity(
    db_conn: AsyncConnection,
) -> None:
    """Ride, walk and flexibility reads share the matcher: none may touch ``raw_summary``."""
    player, planned_id, activity_id = await _seed(db_conn, categories=WATCH_A)
    factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)

    async with factory() as session:
        activity = (
            await session.execute(
                select(Activity)
                .options(without_activity_raw_summary())
                .where(Activity.id == activity_id)
            )
        ).scalar_one()
        planned = await session.get(PlannedWorkout, planned_id)
        assert planned is not None
        for category in (DAY_CATEGORY_CYCLE, DAY_CATEGORY_WALK, "flexibility"):
            assert material_difference(planned, activity, category=category, ftp_watts=200) is None
