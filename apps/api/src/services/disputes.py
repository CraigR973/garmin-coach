"""Mark's disputes, recorded rather than lost in chat (Batch 274).

A **contest** is a bug report from the only user: the figure, the working the app
showed for it (Batch 273's provenance, read from the stored packet), his reason and
the date, with an alert to Craig. A **dissent** is his disagreement with a day's
verdict, kept beside the day and shown in the weekly review, so repeated justified
dissent becomes visible.

**Neither changes anything.** No rollup, verdict, VO2 block or chronic cluster reads
this module or its table; suppressing a contested input is Batch 276, and
``tests/test_batch_274_disputes.py`` pins the boundary so it cannot arrive early.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import Analysis, Dispute
from src.models.profile import Profile
from src.services.nudge_alerts import NudgeAlertService
from src.services.provenance import PROVENANCED_FIGURES, find_provenance

KIND_FIGURE = "figure"
KIND_VERDICT = "verdict"
MAX_REASON_LENGTH = 2000


def _clean_reason(reason: str) -> str:
    cleaned = reason.strip()
    if not cleaned:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Say what looks wrong, so Craig can look into it.",
        )
    return cleaned[:MAX_REASON_LENGTH]


class DisputeService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _owned_analysis(self, player: Profile, analysis_id: uuid.UUID) -> Analysis:
        analysis = await self.session.get(Analysis, analysis_id)
        if analysis is None or analysis.user_id != player.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Read not found")
        return analysis

    async def contest_figure(
        self,
        player: Profile,
        *,
        analysis_id: uuid.UUID,
        figure: str,
        reason: str,
    ) -> Dispute:
        """Record a contested figure with the working the app showed for it."""
        cleaned = _clean_reason(reason)
        analysis = await self._owned_analysis(player, analysis_id)
        entry = find_provenance(analysis.context_packet, figure)
        if figure not in PROVENANCED_FIGURES or entry is None:
            # Contesting a number whose derivation was never shown is guesswork, and
            # a record without its working could not be checked (274.4).
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="This figure has no working to contest.",
            )
        dispute = Dispute(
            user_id=player.id,
            kind=KIND_FIGURE,
            analysis_id=analysis.id,
            subject_date=analysis.subject_date,
            figure=figure,
            snapshot=entry,
            reason=cleaned,
        )
        self.session.add(dispute)
        await self.session.flush()
        await NudgeAlertService(self.session).notify_admin_figure_contest(
            dispute_id=dispute.id,
            label=str(entry.get("label") or figure),
            value=entry.get("value"),
            units=entry.get("units"),
            subject_date=analysis.subject_date,
            reason=cleaned,
            commit=False,
        )
        await self.session.commit()
        await self.session.refresh(dispute)
        return dispute

    async def dissent_from_verdict(
        self,
        player: Profile,
        *,
        subject_date: date,
        reason: str,
    ) -> Dispute:
        """Record "I disagree, and here's why" against a day's verdict."""
        cleaned = _clean_reason(reason)
        analysis = await self.session.scalar(
            select(Analysis)
            .where(
                Analysis.user_id == player.id,
                Analysis.analysis_type == "morning",
                Analysis.subject_date == subject_date,
            )
            .order_by(Analysis.generated_at_utc.desc())
            .limit(1)
        )
        if analysis is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="There is no verdict for that day to disagree with.",
            )
        packet = analysis.context_packet if isinstance(analysis.context_packet, dict) else {}
        raw_verdict = packet.get("verdict")
        verdict: dict[str, Any] = raw_verdict if isinstance(raw_verdict, dict) else {}
        dispute = Dispute(
            user_id=player.id,
            kind=KIND_VERDICT,
            analysis_id=analysis.id,
            subject_date=subject_date,
            figure=None,
            snapshot={
                "status": verdict.get("status") or analysis.verdict,
                "reasons": list(verdict.get("reasons") or []),
                "promptVersion": analysis.prompt_version,
            },
            reason=cleaned,
        )
        self.session.add(dispute)
        await self.session.commit()
        await self.session.refresh(dispute)
        return dispute

    async def between(
        self,
        user_id: uuid.UUID,
        start: date,
        end: date,
        *,
        kind: str | None = None,
    ) -> list[Dispute]:
        query = (
            select(Dispute)
            .where(
                Dispute.user_id == user_id,
                Dispute.subject_date >= start,
                Dispute.subject_date <= end,
            )
            .order_by(Dispute.subject_date.asc(), Dispute.created_at.asc())
        )
        if kind is not None:
            query = query.where(Dispute.kind == kind)
        return list((await self.session.execute(query)).scalars().all())
