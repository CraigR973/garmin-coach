"""Shared database proof for explanatory-only coaching surfaces."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import Analysis, PlannedWorkout
from src.services.training_week import ACTION_AUDIT_TYPES

RowSnapshot = tuple[tuple[str, Any], ...]


@dataclass(frozen=True)
class CoachingMutationSnapshot:
    """Plan rows and verdict/action analyses that speech must not mutate."""

    planned_workouts: tuple[RowSnapshot, ...]
    verdict_or_action_analyses: tuple[RowSnapshot, ...]


def _freeze_rows(rows: list[dict[str, Any]]) -> tuple[RowSnapshot, ...]:
    frozen = [tuple(sorted(row.items())) for row in rows]
    return tuple(sorted(frozen, key=lambda row: str(dict(row).get("id"))))


async def coaching_mutation_snapshot(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> CoachingMutationSnapshot:
    planned = (
        (
            await session.execute(
                select(PlannedWorkout.__table__).where(PlannedWorkout.user_id == user_id)
            )
        )
        .mappings()
        .all()
    )
    verdict_or_action = (
        (
            await session.execute(
                select(Analysis.__table__).where(
                    Analysis.user_id == user_id,
                    or_(
                        Analysis.verdict.is_not(None),
                        Analysis.analysis_type.in_(ACTION_AUDIT_TYPES),
                    ),
                )
            )
        )
        .mappings()
        .all()
    )
    return CoachingMutationSnapshot(
        planned_workouts=_freeze_rows([dict(row) for row in planned]),
        verdict_or_action_analyses=_freeze_rows([dict(row) for row in verdict_or_action]),
    )


async def assert_no_coaching_mutation(
    session: AsyncSession,
    user_id: uuid.UUID,
    before: CoachingMutationSnapshot,
) -> None:
    """Assert a speech-only operation wrote neither plan nor verdict state."""

    after = await coaching_mutation_snapshot(session, user_id)
    assert after.planned_workouts == before.planned_workouts
    assert after.verdict_or_action_analyses == before.verdict_or_action_analyses
