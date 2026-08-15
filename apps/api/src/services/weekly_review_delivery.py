"""Scheduled weekly-review delivery into the rolling coach thread (Batch 185)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import Analysis, BriefMessage
from src.models.profile import Profile
from src.services.brief_chat import ROLE_ASSISTANT
from src.services.nudge_alerts import NudgeAlertService
from src.services.reviews import (
    PERIOD_WEEKLY,
    ReviewClient,
    ReviewService,
    review_bottom_line,
)

ORIGIN_KIND_WEEKLY_REVIEW = "weekly_review"
WEEKLY_REVIEW_FAILURE_MESSAGE = (
    "I couldn't write this week's review just now. "
    "[Open Reviews](/reviews) to try again when you're ready."
)


@dataclass(frozen=True)
class WeeklyReviewDeliveryResult:
    review: Analysis
    generated: bool
    message: BriefMessage
    message_created: bool
    push_recorded: bool


def _aware_utc(moment: datetime | None) -> datetime:
    if moment is None:
        return datetime.now(UTC)
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


class WeeklyReviewDeliveryService:
    """Generate one weekly review, deliver it once, and notify once.

    ``ReviewService.run`` owns period/prompt idempotency. The assistant row is
    deduped by its review anchor and the push uses ``NudgeAlertService``'s
    existing audit-tag rail. Keeping all three writes in one caller-controlled
    transaction lets a retry finish a partially delivered review without a
    second model call.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record_failure(
        self,
        player: Profile,
        *,
        subject_date: date,
        now_utc: datetime | None = None,
        commit: bool = True,
    ) -> tuple[BriefMessage, bool]:
        """Leave one honest, retryable thread turn when generation fails.

        The failure is deliberately not pushed: there is no substantive weekly
        conclusion to notify about. The launcher will surface the unseen turn
        on the next app open, while the operator alert handles intervention.
        """
        message = cast(
            BriefMessage | None,
            await self.session.scalar(
                select(BriefMessage)
                .where(
                    BriefMessage.user_id == player.id,
                    BriefMessage.analysis_id.is_(None),
                    BriefMessage.role == ROLE_ASSISTANT,
                    BriefMessage.origin_kind == ORIGIN_KIND_WEEKLY_REVIEW,
                    BriefMessage.origin_date == subject_date,
                )
                .limit(1)
            ),
        )
        created = message is None
        if message is None:
            message = BriefMessage(
                user_id=player.id,
                analysis_id=None,
                origin_kind=ORIGIN_KIND_WEEKLY_REVIEW,
                origin_date=subject_date,
                role=ROLE_ASSISTANT,
                content=WEEKLY_REVIEW_FAILURE_MESSAGE,
                created_utc=_aware_utc(now_utc).replace(tzinfo=None),
            )
            self.session.add(message)
            await self.session.flush()
        if commit:
            await self.session.commit()
            await self.session.refresh(message)
        return message, created

    async def run(
        self,
        player: Profile,
        *,
        as_of: date,
        client: ReviewClient | None = None,
        now_utc: datetime | None = None,
        commit: bool = True,
    ) -> WeeklyReviewDeliveryResult:
        review_result = await ReviewService(self.session).run(
            player,
            PERIOD_WEEKLY,
            as_of=as_of,
            client=client,
            commit=False,
        )
        review = review_result.review
        conclusion = review_bottom_line(review.output_markdown)
        origin_date = review_result.preview.period_end

        message = cast(
            BriefMessage | None,
            await self.session.scalar(
                select(BriefMessage)
                .where(
                    BriefMessage.user_id == player.id,
                    BriefMessage.role == ROLE_ASSISTANT,
                    BriefMessage.origin_kind == ORIGIN_KIND_WEEKLY_REVIEW,
                    BriefMessage.origin_date == origin_date,
                )
                .limit(1)
            ),
        )
        message_created = message is None
        if message is None:
            sent_at = _aware_utc(now_utc)
            message = BriefMessage(
                user_id=player.id,
                analysis_id=review.id,
                origin_kind=ORIGIN_KIND_WEEKLY_REVIEW,
                origin_date=origin_date,
                role=ROLE_ASSISTANT,
                content=review.output_markdown,
                created_utc=sent_at.replace(tzinfo=None),
            )
            self.session.add(message)
            await self.session.flush()
        elif message.analysis_id != review.id or message.content != review.output_markdown:
            message.analysis_id = review.id
            message.content = review.output_markdown

        push_recorded = await NudgeAlertService(self.session).push_weekly_review(
            player,
            review,
            conclusion=conclusion,
            subject_date=origin_date,
            now_utc=_aware_utc(now_utc),
            commit=False,
        )
        if commit:
            await self.session.commit()
            await self.session.refresh(message)

        return WeeklyReviewDeliveryResult(
            review=review,
            generated=review_result.generated,
            message=message,
            message_created=message_created,
            push_recorded=push_recorded,
        )
