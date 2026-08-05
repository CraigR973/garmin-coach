"""Batch 185: scheduled weekly review -> coach thread -> one conclusion push."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from src.models.coaching import Analysis, BriefMessage
from src.models.profile import Profile, UserRole
from src.services.nudge_alerts import ANALYSIS_TYPE_WEEKLY_REVIEW_PUSH
from src.services.reviews import (
    ANALYSIS_TYPE_WEEKLY,
    ClaudeReviewResult,
)
from src.services.weekly_review_delivery import (
    ORIGIN_KIND_WEEKLY_REVIEW,
    WEEKLY_REVIEW_FAILURE_MESSAGE,
    WeeklyReviewDeliveryService,
)

SUNDAY = date(2026, 8, 2)
WEEK_START = date(2026, 7, 27)


class FakeReviewClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def generate(
        self,
        *,
        context_packet: dict[str, Any],
        user_prompt: str,
    ) -> ClaudeReviewResult:
        self.calls.append({"packet": context_packet, "prompt": user_prompt})
        return ClaudeReviewResult(
            output_markdown=(
                "**Bottom line:** Recovery held steady while the planned load increased.\n\n"
                "**Trends**\n- Sleep held steady across the week.\n\n"
                "**Wins**\n- The quality work landed.\n\n"
                "**Concerns**\n- None beyond normal fatigue.\n\n"
                "**Recommendations**\n- Keep Monday easy."
            ),
            raw_response={"id": "weekly-review-fake"},
            model_name="fake-model",
        )


@pytest.mark.asyncio
async def test_delivery_is_idempotent_across_review_message_and_push(
    db_conn: AsyncConnection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            Profile(
                id=user_id,
                display_name="Weekly Review Test",
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
            )
        )
        await session.commit()

    send = AsyncMock(return_value=1)
    monkeypatch.setattr("src.services.nudge_alerts.send_notification", send)
    client = FakeReviewClient()
    sent_at = datetime(2026, 8, 2, 17, 0, tzinfo=UTC)

    async with factory() as session:
        player = await session.get(Profile, user_id)
        assert player is not None
        service = WeeklyReviewDeliveryService(session)

        first = await service.run(
            player,
            as_of=SUNDAY,
            client=client,
            now_utc=sent_at,
        )
        second = await service.run(
            player,
            as_of=SUNDAY,
            client=client,
            now_utc=sent_at,
        )

        review_count = await session.scalar(
            select(func.count())
            .select_from(Analysis)
            .where(Analysis.analysis_type == ANALYSIS_TYPE_WEEKLY)
        )
        push_count = await session.scalar(
            select(func.count())
            .select_from(Analysis)
            .where(Analysis.analysis_type == ANALYSIS_TYPE_WEEKLY_REVIEW_PUSH)
        )
        messages = (
            (await session.execute(select(BriefMessage).where(BriefMessage.user_id == user_id)))
            .scalars()
            .all()
        )

    assert first.generated is True
    assert first.message_created is True
    assert first.push_recorded is True
    assert second.generated is False
    assert second.message_created is False
    assert second.push_recorded is False
    assert len(client.calls) == 1
    assert review_count == 1
    assert push_count == 1
    assert send.await_count == 1
    assert first.review.subject_date == WEEK_START
    assert len(messages) == 1
    assert messages[0].role == "assistant"
    assert messages[0].analysis_id == first.review.id
    assert messages[0].origin_kind == ORIGIN_KIND_WEEKLY_REVIEW
    assert messages[0].origin_date == SUNDAY
    assert messages[0].content.startswith("**Bottom line:** Recovery held steady")


@pytest.mark.asyncio
async def test_failure_turn_is_retryable_unpushed_and_idempotent(
    db_conn: AsyncConnection,
) -> None:
    factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    async with factory() as session:
        player = Profile(
            id=user_id,
            display_name="Weekly Review Failure",
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.commit()

        service = WeeklyReviewDeliveryService(session)
        first, first_created = await service.record_failure(player, subject_date=SUNDAY)
        second, second_created = await service.record_failure(player, subject_date=SUNDAY)
        count = await session.scalar(
            select(func.count())
            .select_from(BriefMessage)
            .where(
                BriefMessage.user_id == user_id,
                BriefMessage.origin_kind == ORIGIN_KIND_WEEKLY_REVIEW,
            )
        )

    assert first_created is True
    assert second_created is False
    assert first.id == second.id
    assert first.analysis_id is None
    assert first.content == WEEKLY_REVIEW_FAILURE_MESSAGE
    assert "/reviews" in first.content
    assert count == 1
