"""Batch 221 nightly evidence loop and immutable REM assignment tests."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import ManualEntry, Sleep
from src.models.profile import Profile, UserRole
from src.services.experiment_loop import (
    SOURCE_NIGHTLY,
    SOURCE_REM_NIGHT,
    ExperimentLoopService,
)
from src.services.experiment_tracker import (
    SLUG_REM_INTERVENTION,
    ExperimentTrackerService,
)
from src.services.rem_interventions import select_rem_interventions


async def _seed_profile(db_conn: AsyncConnection, user_id: uuid.UUID) -> None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            Profile(
                id=user_id,
                display_name=f"Experiment Loop {user_id.hex[:8]}",
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
            )
        )
        await session.commit()


def test_candidate_dates_begin_forward_only_then_fill_post_start_gaps() -> None:
    loop = ExperimentLoopService(SimpleNamespace())  # type: ignore[arg-type]
    not_started = SimpleNamespace(observations_json={"entries": []})
    started_without_sleep = SimpleNamespace(
        observations_json={"nightlyStartedAt": "2026-08-24", "entries": []}
    )

    assert loop._candidate_dates(not_started, subject_date=date(2026, 8, 24)) == [date(2026, 8, 24)]
    assert loop._candidate_dates(started_without_sleep, subject_date=date(2026, 8, 26)) == [
        date(2026, 8, 24),
        date(2026, 8, 25),
        date(2026, 8, 26),
    ]
    # Regenerating a pre-deploy morning cannot manufacture historical evidence.
    assert loop._candidate_dates(started_without_sleep, subject_date=date(2026, 8, 23)) == []


@pytest.mark.asyncio
async def test_assignment_is_immutable_and_monday_check_in_reads_sunday_assignment(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = await session.get(Profile, user_id)
        assert player is not None
        service = ExperimentLoopService(session)

        prior_actions, prior_rotation = select_rem_interventions(as_of=date(2026, 8, 17))
        prior = await service.ensure_assignment(
            player,
            as_of=date(2026, 8, 17),
            actions=prior_actions,
            rotation=prior_rotation,
            commit=False,
        )
        assert prior is not None
        # A second writer cannot replace what was issued for that period.
        replay = await service.ensure_assignment(
            player,
            as_of=date(2026, 8, 17),
            actions=["replacement", "replacement"],
            rotation=prior_rotation,
            commit=False,
        )
        assert replay == prior

        current_actions, current_rotation = select_rem_interventions(as_of=date(2026, 8, 24))
        current = await service.ensure_assignment(
            player,
            as_of=date(2026, 8, 24),
            actions=current_actions,
            rotation=current_rotation,
            commit=False,
        )
        assert current is not None

        monday_check_in = await service.assignment_for_night(
            player.id,
            wake_date=date(2026, 8, 24),
        )
        tuesday_check_in = await service.assignment_for_night(
            player.id,
            wake_date=date(2026, 8, 25),
        )

        assert monday_check_in == prior
        assert tuesday_check_in == current
        assert monday_check_in.interventions != tuesday_check_in.interventions

        midweek_actions, midweek_rotation = select_rem_interventions(as_of=date(2026, 9, 2))
        midweek = await service.ensure_assignment(
            player,
            as_of=date(2026, 9, 2),
            actions=midweek_actions,
            rotation=midweek_rotation,
            commit=False,
        )
        assert midweek is not None
        assert midweek.window_start == date(2026, 9, 2)
        assert await service.assignment_for_night(player.id, wake_date=date(2026, 9, 2)) is None
        assert await service.assignment_for_night(player.id, wake_date=date(2026, 9, 3)) == midweek


@pytest.mark.asyncio
async def test_nightly_loop_is_idempotent_preserves_human_evidence_and_updates_feedback(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    wake_date = date(2026, 8, 25)
    await _seed_profile(db_conn, user_id)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = await session.get(Profile, user_id)
        assert player is not None
        loop = ExperimentLoopService(session)
        actions, rotation = select_rem_interventions(as_of=date(2026, 8, 24))
        assignment = await loop.ensure_assignment(
            player,
            as_of=date(2026, 8, 24),
            actions=actions,
            rotation=rotation,
            commit=False,
        )
        assert assignment is not None

        tracker = ExperimentTrackerService(session)
        await tracker.seed_defaults(player, commit=False)
        experiments = await tracker.list_experiments(player, seed=False)
        collagen = next(
            row for row in experiments if row.success_criteria_json.get("slug") == "collagen"
        )
        await tracker.add_observation(
            player,
            collagen.id,
            note="Mark noticed an unusually calm evening.",
            on_date=wake_date,
            metrics={"source": "human"},
            commit=False,
        )
        session.add(
            Sleep(
                user_id=user_id,
                calendar_date=wake_date,
                score=77,
                age_adjusted_score=78,
                duration_sec=36_000,
                rem_sleep_sec=7_200,
                awake_sleep_sec=2_400,
                avg_sleep_stress=28,
            )
        )
        manual = ManualEntry(
            user_id=user_id,
            planned_workout_id=None,
            activity_id=None,
            entry_date=wake_date,
            entry_at_utc=datetime(2026, 8, 25, 6, 30),
            actual_workout_json={},
            supplements_json={"summary": "collagen"},
            food_json={},
            sleep_setup_json={},
            rem_intervention_feedback_json={
                "periodLabel": assignment.period_label,
                "responses": [
                    {"interventionId": assignment.interventions[0]["id"], "status": "applied"},
                    {"interventionId": assignment.interventions[1]["id"], "status": "unknown"},
                ],
            },
        )
        session.add(manual)
        await session.flush()

        assert (
            await loop.record_nightly_observations(player, subject_date=wake_date, commit=False)
            == 4
        )
        assert (
            await loop.record_nightly_observations(player, subject_date=wake_date, commit=False)
            == 0
        )

        # A corrected application answer replaces the REM source entry only.
        manual.rem_intervention_feedback_json = {
            **manual.rem_intervention_feedback_json,
            "responses": [
                {
                    "interventionId": assignment.interventions[0]["id"],
                    "status": "not_applied",
                },
                {"interventionId": assignment.interventions[1]["id"], "status": "unknown"},
            ],
        }
        assert (
            await loop.record_nightly_observations(player, subject_date=wake_date, commit=False)
            == 1
        )

        refreshed = await tracker.list_experiments(player, seed=False)
        for experiment in refreshed:
            entries = experiment.observations_json["entries"]
            source_entries = [
                entry
                for entry in entries
                if entry["metrics"].get("source") in {SOURCE_NIGHTLY, SOURCE_REM_NIGHT}
            ]
            assert len(source_entries) == 1
        collagen_entries = collagen.observations_json["entries"]
        assert any(entry["metrics"].get("source") == "human" for entry in collagen_entries)

        rem_experiment = next(
            row
            for row in refreshed
            if row.success_criteria_json.get("slug") == SLUG_REM_INTERVENTION
        )
        rem_entry = rem_experiment.observations_json["entries"][0]
        assert rem_entry["metrics"]["responses"][0]["status"] == "not_applied"

        packet = await loop.packet(player, subject_date=wake_date)
        rem_packet = next(
            row
            for row in packet["experiments"]
            if row["evaluation"]["slug"] == SLUG_REM_INTERVENTION
        )
        assert rem_packet["evaluation"]["recommendation"] == "inconclusive"
        assert rem_packet["conclusion"] == "human_gated_terminal"
        assert packet["rules"]["unknownApplicationMeansNotApplied"] is False
