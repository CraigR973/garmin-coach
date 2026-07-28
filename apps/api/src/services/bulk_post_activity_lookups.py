"""Bulk lookup helpers for post-activity read selection.

The app deliberately keeps historical analysis rows (Decision #219). These
helpers preserve the existing latest-wins read rule while avoiding one query per
activity/source row.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import Analysis, ManualEntry, PostActivityGenerationStatus


async def latest_analyses_by_activity(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    activity_ids: Sequence[uuid.UUID],
    analysis_type: str | None = None,
) -> dict[uuid.UUID, Analysis]:
    if not activity_ids:
        return {}

    criteria = [
        Analysis.user_id == user_id,
        Analysis.activity_id.in_(activity_ids),
    ]
    if analysis_type is not None:
        criteria.append(Analysis.analysis_type == analysis_type)

    rows = (
        (
            await session.execute(
                select(Analysis)
                .where(*criteria)
                .order_by(
                    Analysis.activity_id.asc(),
                    desc(Analysis.generated_at_utc),
                    desc(Analysis.created_at),
                )
            )
        )
        .scalars()
        .all()
    )

    latest: dict[uuid.UUID, Analysis] = {}
    for row in rows:
        if row.activity_id is not None and row.activity_id not in latest:
            latest[row.activity_id] = row
    return latest


async def latest_morning_analyses_by_date(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    subject_dates: Sequence[date],
) -> dict[date, Analysis]:
    if not subject_dates:
        return {}

    rows = (
        (
            await session.execute(
                select(Analysis)
                .where(
                    Analysis.user_id == user_id,
                    Analysis.analysis_type == "morning",
                    Analysis.subject_date.in_(subject_dates),
                )
                .order_by(
                    Analysis.subject_date.asc(),
                    desc(Analysis.generated_at_utc),
                    desc(Analysis.created_at),
                )
            )
        )
        .scalars()
        .all()
    )

    latest: dict[date, Analysis] = {}
    for row in rows:
        if row.subject_date not in latest:
            latest[row.subject_date] = row
    return latest


async def latest_checkins_by_activity(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    activity_ids: Sequence[uuid.UUID],
) -> dict[uuid.UUID, ManualEntry]:
    if not activity_ids:
        return {}

    rows = (
        (
            await session.execute(
                select(ManualEntry)
                .where(
                    ManualEntry.user_id == user_id,
                    ManualEntry.activity_id.in_(activity_ids),
                )
                .order_by(
                    ManualEntry.activity_id.asc(),
                    desc(ManualEntry.entry_at_utc),
                    desc(ManualEntry.created_at),
                )
            )
        )
        .scalars()
        .all()
    )

    latest: dict[uuid.UUID, ManualEntry] = {}
    for row in rows:
        if row.activity_id is not None and row.activity_id not in latest:
            latest[row.activity_id] = row
    return latest


async def generation_statuses_by_activity(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    activity_ids: Sequence[uuid.UUID],
) -> dict[uuid.UUID, PostActivityGenerationStatus]:
    if not activity_ids:
        return {}

    rows = (
        (
            await session.execute(
                select(PostActivityGenerationStatus).where(
                    PostActivityGenerationStatus.user_id == user_id,
                    PostActivityGenerationStatus.activity_id.in_(activity_ids),
                )
            )
        )
        .scalars()
        .all()
    )
    return {row.activity_id: row for row in rows}
