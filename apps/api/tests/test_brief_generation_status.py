"""Batch 141: brief-generation failure signal — service upsert + envelope shape."""

from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import MagicMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from src.config import settings
from src.models.coaching import BriefGenerationStatus
from src.models.profile import Profile, UserRole
from src.routers.daily_loop import BriefGenerationStatusOut, _serialize_brief_generation
from src.services.brief_generation_status import (
    STATUS_FAILED,
    STATUS_READY,
    BriefGenerationStatusService,
)
from src.services.nudge_alerts import NudgeAlertService


def _failed_row() -> BriefGenerationStatus:
    return BriefGenerationStatus(
        user_id=uuid.uuid4(),
        subject_date=date(2026, 7, 21),
        status=STATUS_FAILED,
        reason="billing",
    )


def test_serialize_prefers_ready_when_analysis_exists() -> None:
    # A real brief on the day is authoritative — a stale failed row never wins.
    out = _serialize_brief_generation(_failed_row(), has_analysis=True)
    assert out == BriefGenerationStatusOut(status="ready", reason=None)


def test_serialize_surfaces_failure_when_no_analysis() -> None:
    out = _serialize_brief_generation(_failed_row(), has_analysis=False)
    assert out is not None
    assert out.status == "failed"
    assert out.reason == "billing"


def test_serialize_is_none_when_no_row_and_no_analysis() -> None:
    assert _serialize_brief_generation(None, has_analysis=False) is None


@pytest.mark.asyncio
async def test_admin_alert_no_push_when_operator_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """141.3 decision: the log event always fires; the push is a no-op until Craig
    is seeded (admin_alert_user_id empty), so it never touches the DB session."""
    monkeypatch.setattr(settings, "admin_alert_user_id", "")
    sent = await NudgeAlertService(MagicMock()).notify_admin_generation_failure(
        reason="billing", subject_date=date(2026, 7, 21)
    )
    assert sent is False


@pytest.mark.asyncio
async def test_status_service_upserts_in_place(db_conn: AsyncConnection) -> None:
    """generating → failed → ready all update one row (no duplicates), reason follows."""
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    subject_date = date(2026, 7, 21)

    async with session_factory() as session:
        session.add(
            Profile(
                id=user_id,
                display_name="Status Test",
                pin_hash="x" * 60,
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
            )
        )
        await session.commit()

    async with session_factory() as session:
        service = BriefGenerationStatusService(session)
        await service.mark_generating(user_id, subject_date)
        await service.mark_failed(user_id, subject_date, reason="billing")

    async with session_factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(BriefGenerationStatus)
            .where(BriefGenerationStatus.user_id == user_id)
        )
        assert count == 1
        row = await BriefGenerationStatusService(session).get(user_id, subject_date)
        assert row is not None
        assert row.status == STATUS_FAILED
        assert row.reason == "billing"

    async with session_factory() as session:
        await BriefGenerationStatusService(session).mark_ready(user_id, subject_date)

    async with session_factory() as session:
        row = await BriefGenerationStatusService(session).get(user_id, subject_date)
        assert row is not None
        assert row.status == STATUS_READY
        assert row.reason is None
