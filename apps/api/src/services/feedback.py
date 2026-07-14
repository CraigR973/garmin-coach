"""Rate & correct any AI summary — the feedback primitive (Batch 64).

Every AI summary the app generates is one ``analyses`` row (Decision #137), so
one feedback primitive keyed to ``analysis_id`` covers the whole app: the morning
verdict, the post-``workout``/``walk``/``strength``/``flexibility`` reads, and the
``weekly``/``monthly``/``seasonal`` reviews. The rating is the doorway; the
optional free-text ``correction_text`` is the payload that feeds the next read
forward (see :mod:`src.services.morning_analysis`).

The write is **user-scoped**: a caller can only rate their own analysis. The
service raises 404 when the analysis does not exist and 403 when it exists but
belongs to another profile, so ownership can never be spoofed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import Analysis, Feedback
from src.models.profile import Profile

KIND_SUMMARY = "summary"
KIND_SUGGESTION = "suggestion"

# The two axes, chosen per content type (a suggestion can't be "inaccurate").
# Ordered best → worst; the frontend reveals the correction box on a negative tap.
RATINGS_BY_KIND: dict[str, tuple[str, ...]] = {
    KIND_SUMMARY: ("spot_on", "a_bit_off", "way_off"),
    KIND_SUGGESTION: ("agree", "not_for_me", "already_doing"),
}

# One-tap "what's off" reasons, scoped by kind (Batch 118). Revealed alongside
# the free-text box on a negative tap; the frontend also validates against this
# list so a stale client can't send a reason that no longer applies to the kind.
REASON_TAGS_BY_KIND: dict[str, tuple[str, ...]] = {
    KIND_SUMMARY: ("sleep_read", "load_read", "thermal_read", "plan_mismatch", "other"),
    KIND_SUGGESTION: ("too_cautious", "too_aggressive", "bad_timing", "not_practical", "other"),
}

# How many recent corrections feed the next read (kept small — n=1, no aggregation).
RECENT_CORRECTIONS_LIMIT = 5


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass(frozen=True)
class RecentCorrection:
    """One prior correction, surfaced into the next generation's context packet."""

    analysis_id: uuid.UUID
    analysis_type: str
    subject_date: date
    kind: str
    rating: str
    correction_text: str
    reason_tags: tuple[str, ...]
    created_utc: datetime

    def to_packet(self) -> dict[str, object]:
        return {
            "analysisId": str(self.analysis_id),
            "analysisType": self.analysis_type,
            "subjectDate": self.subject_date.isoformat(),
            "kind": self.kind,
            "rating": self.rating,
            "correction": self.correction_text,
            "reasonTags": list(self.reason_tags),
            "createdAtUtc": self.created_utc.isoformat() + "Z",
        }


class FeedbackService:
    def __init__(self, session: AsyncSession):
        self.session = session

    def _validate(self, kind: str, rating: str, reason_tags: list[str]) -> None:
        allowed = RATINGS_BY_KIND.get(kind)
        if allowed is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown feedback kind '{kind}'.",
            )
        if rating not in allowed:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Rating '{rating}' is not valid for kind '{kind}'.",
            )
        allowed_reasons = REASON_TAGS_BY_KIND[kind]
        invalid_reasons = [tag for tag in reason_tags if tag not in allowed_reasons]
        if invalid_reasons:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Reason tag(s) {invalid_reasons} are not valid for kind '{kind}'.",
            )

    async def _owned_analysis(self, player: Profile, analysis_id: uuid.UUID) -> Analysis:
        analysis = await self.session.scalar(select(Analysis).where(Analysis.id == analysis_id))
        if analysis is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")
        if analysis.user_id != player.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only rate your own analysis",
            )
        return analysis

    async def upsert(
        self,
        player: Profile,
        analysis_id: uuid.UUID,
        *,
        kind: str,
        rating: str,
        correction_text: str | None,
        reason_tags: list[str] | None = None,
        commit: bool = True,
    ) -> Feedback:
        """Create or replace this user's feedback for one analysis (one row per pair)."""
        tags = reason_tags or []
        self._validate(kind, rating, tags)
        await self._owned_analysis(player, analysis_id)

        cleaned = correction_text.strip() if correction_text else None
        row = await self.session.scalar(
            select(Feedback).where(
                Feedback.user_id == player.id,
                Feedback.analysis_id == analysis_id,
            )
        )
        if row is None:
            row = Feedback(
                user_id=player.id,
                analysis_id=analysis_id,
                kind=kind,
                rating=rating,
                correction_text=cleaned or None,
                reason_tags=tags,
                created_utc=_utcnow(),
            )
            self.session.add(row)
        else:
            row.kind = kind
            row.rating = rating
            row.correction_text = cleaned or None
            row.reason_tags = tags
            row.created_utc = _utcnow()

        if commit:
            await self.session.commit()
            await self.session.refresh(row)
        else:
            await self.session.flush()
        return row

    async def feedback_for_analyses(
        self, user_id: uuid.UUID, analysis_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, Feedback]:
        """Map ``analysis_id -> Feedback`` for the given analyses, this user only."""
        if not analysis_ids:
            return {}
        rows = (
            (
                await self.session.execute(
                    select(Feedback).where(
                        Feedback.user_id == user_id,
                        Feedback.analysis_id.in_(tuple(analysis_ids)),
                    )
                )
            )
            .scalars()
            .all()
        )
        return {row.analysis_id: row for row in rows}

    async def recent_corrections(
        self, user_id: uuid.UUID, *, limit: int = RECENT_CORRECTIONS_LIMIT
    ) -> list[RecentCorrection]:
        """The most recent free-text/reason-tag corrections for this user, newest first.

        Only rows with a non-empty ``correction_text`` or at least one
        ``reason_tags`` entry — a bare rating is a signal, but the correction
        (text and/or tags) is the payload the next read acts on.
        """
        rows = (
            await self.session.execute(
                select(Feedback, Analysis)
                .join(Analysis, Feedback.analysis_id == Analysis.id)
                .where(
                    Feedback.user_id == user_id,
                    or_(
                        Feedback.correction_text.isnot(None),
                        func.jsonb_array_length(Feedback.reason_tags) > 0,
                    ),
                )
                .order_by(Feedback.created_utc.desc())
                .limit(limit)
            )
        ).all()
        corrections: list[RecentCorrection] = []
        for feedback, analysis in rows:
            text = (feedback.correction_text or "").strip()
            tags = tuple(feedback.reason_tags or [])
            if not text and not tags:
                continue
            corrections.append(
                RecentCorrection(
                    analysis_id=feedback.analysis_id,
                    analysis_type=analysis.analysis_type,
                    subject_date=analysis.subject_date,
                    kind=feedback.kind,
                    rating=feedback.rating,
                    correction_text=text,
                    reason_tags=tags,
                    created_utc=feedback.created_utc,
                )
            )
        return corrections
