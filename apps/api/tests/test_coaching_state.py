from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from src.auth import get_current_user
from src.database import get_db
from src.main import app
from src.models.coaching import KnowledgeBase, PlannedWorkout
from src.models.profile import Profile, UserRole


def _db_override(session_factory: async_sessionmaker[AsyncSession]):
    async def _override() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    return _override


@pytest.mark.asyncio
async def test_get_coaching_state_seeds_defaults_and_returns_envelope(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()

    async with session_factory() as session:
        user = Profile(
            id=user_id,
            display_name="Coach State Test",
            pin_hash="x" * 60,
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(user)
        await session.commit()

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _db_override(session_factory)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/admin/coaching-state")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["errors"] == []
    assert payload["meta"]["generatedAtUtc"].endswith("Z")
    assert {entry["section"] for entry in payload["data"]["knowledgeBaseSections"]} >= {
        "profile",
        "data_quality_rules",
        "age_adjustment",
        "sleep_protocol",
        "training_plan",
        "active_hypotheses",
    }
    assert len(payload["data"]["planBlocks"]) == 13
    assert payload["data"]["plannedWorkouts"]


@pytest.mark.asyncio
async def test_update_knowledge_base_section_creates_new_active_version(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()

    async with session_factory() as session:
        user = Profile(
            id=user_id,
            display_name="KB Update Test",
            pin_hash="x" * 60,
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(user)
        await session.commit()

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _db_override(session_factory)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            seed_response = await client.get("/api/v1/admin/coaching-state")
            assert seed_response.status_code == 200

            response = await client.put(
                "/api/v1/admin/coaching-state/knowledge-base/sleep_protocol",
                json={
                    "source": "test_override",
                    "content": {
                        "preCoolTemperatureC": 16.5,
                        "sealTargetTime": "21:50",
                    },
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text

    async with session_factory() as session:
        records = (
            (
                await session.execute(
                    select(KnowledgeBase)
                    .where(
                        KnowledgeBase.user_id == user_id,
                        KnowledgeBase.section == "sleep_protocol",
                    )
                    .order_by(KnowledgeBase.version.desc())
                )
            )
            .scalars()
            .all()
        )

    assert len(records) == 2
    assert records[0].version == 2
    assert records[0].is_active is True
    assert records[0].content["sealTargetTime"] == "21:50"
    assert records[1].is_active is False


@pytest.mark.asyncio
async def test_override_planned_workout_preserves_prior_versions(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()

    async with session_factory() as session:
        user = Profile(
            id=user_id,
            display_name="Workout Override Test",
            pin_hash="x" * 60,
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(user)
        await session.commit()

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _db_override(session_factory)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            seed_response = await client.get("/api/v1/admin/coaching-state")
            assert seed_response.status_code == 200

            seed_payload = seed_response.json()
            workout_date = next(
                workout["workoutDate"]
                for workout in seed_payload["data"]["plannedWorkouts"]
                if workout["isActive"] is True
            )

            response = await client.put(
                f"/api/v1/admin/coaching-state/planned-workouts/{workout_date}",
                json={
                    "title": "VO2 Revision for Fatigue",
                    "workoutType": "bike_vo2",
                    "status": "planned",
                    "plannedDurationMin": 48,
                    "intensityTarget": "95-100% FTP",
                    "structuredWorkout": {
                        "format": "bike",
                        "steps": [
                            {"label": "Warm-up", "minutes": 12},
                            {"label": "Main set", "repeats": 6, "pattern": "2 min on / 3 min easy"},
                        ],
                    },
                    "source": "test_override",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text

    async with session_factory() as session:
        records = (
            (
                await session.execute(
                    select(PlannedWorkout)
                    .where(
                        PlannedWorkout.user_id == user_id,
                        PlannedWorkout.workout_date == date.fromisoformat(workout_date),
                    )
                    .order_by(PlannedWorkout.version.desc())
                )
            )
            .scalars()
            .all()
        )

    assert len(records) == 2
    assert records[0].version == 2
    assert records[0].is_active is True
    assert records[0].title == "VO2 Revision for Fatigue"
    assert records[1].is_active is False
