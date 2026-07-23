"""Batch 141: track a day's morning-brief generation state.

The check-in generate path (``routers/daily_loop._generate_brief_after_checkin``)
upserts one row per ``(user, subject_date)``: ``generating`` when scheduled, then
``ready`` on success or ``failed`` (+ classified ``reason``) on error. The
daily-loop envelope reads it so a failed generation surfaces as a retryable error
instead of the pre-141 endless "Writing your brief" spinner (which only ever
cleared when an analysis appeared, so a failure hung forever).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import BriefGenerationStatus

STATUS_GENERATING = "generating"
STATUS_READY = "ready"
STATUS_FAILED = "failed"


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class BriefGenerationStatusService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, user_id: uuid.UUID, subject_date: date) -> BriefGenerationStatus | None:
        row: BriefGenerationStatus | None = await self.session.scalar(
            select(BriefGenerationStatus).where(
                BriefGenerationStatus.user_id == user_id,
                BriefGenerationStatus.subject_date == subject_date,
            )
        )
        return row

    async def mark(
        self,
        user_id: uuid.UUID,
        subject_date: date,
        status: str,
        *,
        reason: str | None = None,
        commit: bool = True,
    ) -> BriefGenerationStatus:
        row = await self.get(user_id, subject_date)
        if row is None:
            row = BriefGenerationStatus(
                user_id=user_id,
                subject_date=subject_date,
                status=status,
                reason=reason,
            )
            self.session.add(row)
        else:
            row.status = status
            row.reason = reason
            row.updated_at = _utcnow()
        if commit:
            await self.session.commit()
        return row

    async def mark_generating(
        self, user_id: uuid.UUID, subject_date: date, *, commit: bool = True
    ) -> BriefGenerationStatus:
        return await self.mark(user_id, subject_date, STATUS_GENERATING, commit=commit)

    async def mark_ready(
        self, user_id: uuid.UUID, subject_date: date, *, commit: bool = True
    ) -> BriefGenerationStatus:
        return await self.mark(user_id, subject_date, STATUS_READY, commit=commit)

    async def mark_failed(
        self,
        user_id: uuid.UUID,
        subject_date: date,
        *,
        reason: str,
        commit: bool = True,
    ) -> BriefGenerationStatus:
        return await self.mark(user_id, subject_date, STATUS_FAILED, reason=reason, commit=commit)
