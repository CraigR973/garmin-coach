"""Batch 336.1 — the ramp test sets his FTP (CI330-02).

Plan No. 3 tells him his new FTP is three-quarters of the best minute he held in the ramp
test, and to set it in Zwift. Zwift sets the trainer from its own FTP, but the app grades
every ride, quotes W/kg and builds every target from the profile's ``ftpWatts``, which
nothing changed: from 22 Oct an ERG-perfect interval at a new FTP 7% either side of the
old one read "under" or "over". After a ramp test Home now offers the new FTP in one tap,
and every FTP read in the app follows the profile.

* **The rule:** ``round(0.75 × best minute)``, the best minute being Garmin's
  ``maxAvgPower_60`` from the test's ride (the activity linked to the plan row by its
  post-ride generation status or read).
* **Zwift's own number may differ by a few watts** (it works the FTP out from its own
  recording: 267 W against the app's 265 W on 20 Oct), and the two must hold the same
  number, so he can enter Zwift's instead, within 10% of the app's.
* **One decision per test**, recorded as the profile version's ``source``
  (``ramp_test_2026_10_20``, the convention of the 20 Oct write; ``…_kept`` when he keeps
  his FTP), so a decided test is never offered again. The offer stands 7 days.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Final, Literal

import structlog
from fastapi import HTTPException, status
from sqlalchemy import select, union
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import (
    Activity,
    Analysis,
    KnowledgeBase,
    PlannedWorkout,
    PostActivityGenerationStatus,
)
from src.models.profile import Profile
from src.services.coaching_state import CoachingStateService

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

#: Plan No. 3's own rule: "your new FTP is three-quarters of the best minute you held".
RAMP_TEST_FTP_FACTOR: Final = 0.75
#: Days after the test that Home offers its result.
OFFER_DAYS: Final = 7
#: How far his own (Zwift's) number may sit from the app's: a typo guard, not a rule.
OWN_NUMBER_TOLERANCE: Final = 0.10
PROFILE_SECTION: Final = "profile"
SOURCE_PREFIX: Final = "ramp_test_"
KEPT_SUFFIX: Final = "_kept"
#: Garmin's best one-minute power in the activity summary.
BEST_MINUTE_KEY: Final = "maxAvgPower_60"

Choice = Literal["set", "keep"]


def ftp_from_best_minute(best_minute_watts: float) -> int:
    """Three-quarters of the best minute, to the nearest watt (half up)."""
    return int(best_minute_watts * RAMP_TEST_FTP_FACTOR + 0.5)


def decision_source(test_date: date, *, kept: bool = False) -> str:
    """The profile version's ``source`` that records his decision on one test."""
    return f"{SOURCE_PREFIX}{test_date:%Y_%m_%d}{KEPT_SUFFIX if kept else ''}"


def own_number_range(ftp_watts: int) -> tuple[int, int]:
    """The FTPs he may enter instead of the app's number."""
    margin = round(ftp_watts * OWN_NUMBER_TOLERANCE)
    return ftp_watts - margin, ftp_watts + margin


@dataclass(frozen=True, slots=True)
class FtpTestOffer:
    planned_workout_id: uuid.UUID
    test_date: date
    best_minute_watts: int
    #: The app's number: three-quarters of the best minute.
    ftp_watts: int
    current_ftp_watts: int | None

    @property
    def own_number_range(self) -> tuple[int, int]:
        return own_number_range(self.ftp_watts)


@dataclass(frozen=True, slots=True)
class FtpTestDecision:
    choice: Choice
    test_date: date
    ftp_watts: int | None
    previous_ftp_watts: int | None


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


class FtpTestService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def offer(self, user_id: uuid.UUID, today: date) -> FtpTestOffer | None:
        """The newest ramp test of the last 7 days that waits for his decision, if any."""
        test = (
            await self.session.execute(
                select(PlannedWorkout.id, PlannedWorkout.workout_date)
                .where(
                    PlannedWorkout.user_id == user_id,
                    PlannedWorkout.is_active.is_(True),
                    PlannedWorkout.status == "completed",
                    PlannedWorkout.structured_workout["test"].astext == "ramp",
                    PlannedWorkout.workout_date <= today,
                    PlannedWorkout.workout_date > today - timedelta(days=OFFER_DAYS),
                )
                .order_by(PlannedWorkout.workout_date.desc())
                .limit(1)
            )
        ).first()
        if test is None:
            return None
        workout_id, test_date = test
        decided = await self.session.scalar(
            select(KnowledgeBase.id)
            .where(
                KnowledgeBase.user_id == user_id,
                KnowledgeBase.section == PROFILE_SECTION,
                KnowledgeBase.source.like(f"{decision_source(test_date)}%"),
            )
            .limit(1)
        )
        if decided is not None:
            return None
        rides = union(
            select(PostActivityGenerationStatus.activity_id).where(
                PostActivityGenerationStatus.user_id == user_id,
                PostActivityGenerationStatus.planned_workout_id == workout_id,
            ),
            select(Analysis.activity_id).where(
                Analysis.user_id == user_id,
                Analysis.planned_workout_id == workout_id,
                Analysis.activity_id.is_not(None),
            ),
        ).subquery()
        minutes = (
            await self.session.execute(
                select(Activity.raw_summary[BEST_MINUTE_KEY].astext).where(
                    Activity.user_id == user_id,
                    Activity.id.in_(select(rides.c[0])),
                )
            )
        ).scalars()
        best = max((n for n in (_number(value) for value in minutes) if n is not None), default=None)
        if best is None:
            return None
        return FtpTestOffer(
            planned_workout_id=workout_id,
            test_date=test_date,
            best_minute_watts=int(best + 0.5),
            ftp_watts=ftp_from_best_minute(best),
            current_ftp_watts=await self._current_ftp(user_id),
        )

    async def decide(
        self,
        player: Profile,
        *,
        planned_workout_id: uuid.UUID,
        choice: Choice,
        today: date,
        ftp_watts: int | None = None,
    ) -> FtpTestDecision:
        """Set his FTP from the test, or keep the one he has; either way, decided."""
        offer = await self.offer(player.id, today)
        if offer is None or offer.planned_workout_id != planned_workout_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No ramp test result is waiting for a decision.",
            )
        content = dict(await self._profile_content(player.id))
        previous = offer.current_ftp_watts
        if choice == "keep":
            new_ftp = previous
        else:
            new_ftp = offer.ftp_watts if ftp_watts is None else ftp_watts
            low, high = offer.own_number_range
            if not low <= new_ftp <= high:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"Enter an FTP between {low} and {high} W.",
                )
            content["ftpWatts"] = new_ftp
        await CoachingStateService(self.session).update_knowledge_base_section(
            player=player,
            section=PROFILE_SECTION,
            content=content,
            source=decision_source(offer.test_date, kept=choice == "keep"),
        )
        log.info(
            "ftp_from_ramp_test",
            profile_id=str(player.id),
            test_date=offer.test_date.isoformat(),
            choice=choice,
            best_minute_watts=offer.best_minute_watts,
            app_ftp_watts=offer.ftp_watts,
            ftp_watts=new_ftp,
            previous_ftp_watts=previous,
        )
        return FtpTestDecision(
            choice=choice,
            test_date=offer.test_date,
            ftp_watts=new_ftp,
            previous_ftp_watts=previous,
        )

    async def _profile_content(self, user_id: uuid.UUID) -> dict[str, Any]:
        content = await self.session.scalar(
            select(KnowledgeBase.content).where(
                KnowledgeBase.user_id == user_id,
                KnowledgeBase.section == PROFILE_SECTION,
                KnowledgeBase.is_active.is_(True),
            )
        )
        return dict(content) if isinstance(content, dict) else {}

    async def _current_ftp(self, user_id: uuid.UUID) -> int | None:
        value = await self.session.scalar(
            select(KnowledgeBase.content["ftpWatts"].astext).where(
                KnowledgeBase.user_id == user_id,
                KnowledgeBase.section == PROFILE_SECTION,
                KnowledgeBase.is_active.is_(True),
            )
        )
        number = _number(value)
        return int(number) if number is not None else None
