"""Tests for Batch 17.4 experiment tracker lifecycle."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import Analysis, Experiment
from src.models.profile import Profile, UserRole
from src.services.experiment_tracker import (
    AUDIT_TYPE_EXPERIMENT,
    DEFAULT_EXPERIMENTS,
    STATUS_ACTIVE,
    STATUS_CONCLUDED,
    STATUS_PAUSED,
    ExperimentTrackerService,
    can_transition,
)

# ---------------------------------------------------------------------------
# Pure transition rules
# ---------------------------------------------------------------------------


def test_can_transition_matrix() -> None:
    assert can_transition(STATUS_ACTIVE, STATUS_PAUSED)
    assert can_transition(STATUS_PAUSED, STATUS_ACTIVE)
    assert can_transition(STATUS_ACTIVE, STATUS_CONCLUDED)
    assert can_transition(STATUS_PAUSED, STATUS_CONCLUDED)
    assert can_transition(STATUS_ACTIVE, STATUS_ACTIVE)  # no-op allowed
    # Concluded is terminal.
    assert not can_transition(STATUS_CONCLUDED, STATUS_ACTIVE)
    assert not can_transition(STATUS_CONCLUDED, STATUS_PAUSED)
    # Unknown status rejected.
    assert not can_transition(STATUS_ACTIVE, "bogus")


# ---------------------------------------------------------------------------
# DB-backed lifecycle
# ---------------------------------------------------------------------------


async def _seed_profile(db_conn: AsyncConnection, user_id: uuid.UUID) -> None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            Profile(
                id=user_id,
                display_name=f"Experiment Test {user_id.hex[:8]}",
                pin_hash="x" * 60,
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_seed_defaults_is_idempotent(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExperimentTrackerService(session)

        created = await service.seed_defaults(user)
        assert len(created) == len(DEFAULT_EXPERIMENTS)

        # Second seed creates nothing.
        again = await service.seed_defaults(user)
        assert again == []

        rows = (
            (await session.execute(select(Experiment).where(Experiment.user_id == user_id)))
            .scalars()
            .all()
        )
        assert len(rows) == len(DEFAULT_EXPERIMENTS)
        slugs = {r.success_criteria_json.get("slug") for r in rows}
        assert slugs == {d.slug for d in DEFAULT_EXPERIMENTS}


@pytest.mark.asyncio
async def test_list_experiments_seeds_and_filters(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExperimentTrackerService(session)

        all_active = await service.list_experiments(user, status_filter=STATUS_ACTIVE)
        assert len(all_active) == len(DEFAULT_EXPERIMENTS)

        none_paused = await service.list_experiments(user, status_filter=STATUS_PAUSED)
        assert none_paused == []


@pytest.mark.asyncio
async def test_lifecycle_pause_resume_conclude_with_audit(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExperimentTrackerService(session)

        experiment = await service.create_experiment(
            user, title="Magnesium before bed", hypothesis="Improves deep sleep."
        )
        assert experiment.status == STATUS_ACTIVE

        paused = await service.update_status(user, experiment.id, new_status=STATUS_PAUSED)
        assert paused.status == STATUS_PAUSED

        resumed = await service.update_status(user, experiment.id, new_status=STATUS_ACTIVE)
        assert resumed.status == STATUS_ACTIVE

        concluded = await service.update_status(
            user,
            experiment.id,
            new_status=STATUS_CONCLUDED,
            outcome="supported",
            note="Deep sleep up 12 min.",
            on_date=date(2026, 6, 22),
        )
        assert concluded.status == STATUS_CONCLUDED
        assert concluded.observations_json["outcome"] == "supported"
        assert concluded.end_date == date(2026, 6, 22)

        audit = (
            (
                await session.execute(
                    select(Analysis).where(
                        Analysis.user_id == user_id,
                        Analysis.analysis_type == AUDIT_TYPE_EXPERIMENT,
                    )
                )
            )
            .scalars()
            .all()
        )
        # create + 3 status changes = 4 audit rows (defaults were not seeded here).
        assert len(audit) == 4


@pytest.mark.asyncio
async def test_conclude_requires_outcome(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExperimentTrackerService(session)
        experiment = await service.create_experiment(
            user, title="Test", hypothesis="Test hypothesis."
        )
        with pytest.raises(HTTPException) as exc:
            await service.update_status(user, experiment.id, new_status=STATUS_CONCLUDED)
        assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_concluded_is_terminal(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExperimentTrackerService(session)
        experiment = await service.create_experiment(
            user, title="Test", hypothesis="Test hypothesis."
        )
        await service.update_status(
            user, experiment.id, new_status=STATUS_CONCLUDED, outcome="refuted"
        )
        with pytest.raises(HTTPException) as exc:
            await service.update_status(user, experiment.id, new_status=STATUS_ACTIVE)
        assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_add_observation_appends_and_rejects_when_concluded(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExperimentTrackerService(session)
        experiment = await service.create_experiment(
            user, title="Test", hypothesis="Test hypothesis."
        )
        updated = await service.add_observation(
            user, experiment.id, note="Slept 7h", metrics={"deepMin": 70}
        )
        assert len(updated.observations_json["entries"]) == 1
        updated = await service.add_observation(user, experiment.id, note="Slept 6h")
        assert len(updated.observations_json["entries"]) == 2

        await service.update_status(
            user, experiment.id, new_status=STATUS_CONCLUDED, outcome="inconclusive"
        )
        with pytest.raises(HTTPException) as exc:
            await service.add_observation(user, experiment.id, note="too late")
        assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_cross_user_experiment_is_not_found(db_conn: AsyncConnection) -> None:
    owner_id = uuid.uuid4()
    other_id = uuid.uuid4()
    await _seed_profile(db_conn, owner_id)
    await _seed_profile(db_conn, other_id)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        owner = await session.get(Profile, owner_id)
        other = await session.get(Profile, other_id)
        assert owner is not None and other is not None
        service = ExperimentTrackerService(session)
        experiment = await service.create_experiment(
            owner, title="Private", hypothesis="Mine only."
        )
        with pytest.raises(HTTPException) as exc:
            await service.update_status(other, experiment.id, new_status=STATUS_PAUSED)
        assert exc.value.status_code == 404
