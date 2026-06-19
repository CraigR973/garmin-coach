"""In-app survey endpoints (``/api/v1/surveys``).

Backs the snooze-able "Week 1 pulse" modal. Two endpoints:

- ``GET  /{survey_key}/status``   → whether the caller has already completed it
- ``POST /{survey_key}/response`` → record a (de-identified) response + mark done

Storage is the hybrid model (see ``models/survey.py``): the answers land in
``survey_responses`` with the caller's active league ids auto-tagged but no
identity, while a separate ``survey_completions`` row (player id only, never
joined to the answers) gates the client nag. ``contact_player_id`` is set only
when the caller opts in to being contacted.
"""

from __future__ import annotations

from typing import Annotated, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import CurrentPlayer
from src.database import get_db
from src.models.league_membership import LeagueMembership
from src.models.survey import WEEK1_PULSE_KEY, SurveyCompletion, SurveyResponse
from src.rate_limit import limiter, per_player_key

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/surveys", tags=["surveys"])

# Only known survey keys are accepted; unknown keys 404 so the table can't be
# seeded with arbitrary survey buckets through the public API.
_KNOWN_SURVEYS = frozenset({WEEK1_PULSE_KEY})


class SurveyStatusResponse(BaseModel):
    completed: bool


class Week1Answers(BaseModel):
    """Answers for the Week 1 pulse (Q2–Q7 + the Scotland bonus, Q9).

    Q1 (which league) and Q8 (name) are intentionally absent: league is
    auto-tagged server-side and identity is handled by the contact opt-in.
    """

    model_config = {"extra": "forbid"}

    q2_overall: int = Field(ge=1, le=5)
    q3_frequency: Literal["several_daily", "daily", "few_days", "barely"]
    q4_notifications: Literal["too_many", "about_right", "too_few", "turned_off", "none_received"]
    q5_missed_deadline: Literal["no", "forgot", "time_confused", "other"]
    q6_biggest_annoyance: Literal[
        "leaderboard",
        "league_switching",
        "live_scores",
        "predictions",
        "notifications",
        "nothing",
        "other",
    ]
    q6_other: str | None = Field(default=None, max_length=500)
    q7_open: str | None = Field(default=None, max_length=2000)
    q9_scotland: str | None = Field(default=None, max_length=200)


class Week1SubmitRequest(BaseModel):
    model_config = {"extra": "forbid"}

    answers: Week1Answers
    # Hybrid model: when true, the caller's id is stored on the response so the
    # admin can follow up; otherwise the response stays anonymous.
    contact_ok: bool = False


def _require_known(survey_key: str) -> None:
    if survey_key not in _KNOWN_SURVEYS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown survey")


@router.get("/{survey_key}/status", response_model=SurveyStatusResponse)
@limiter.limit("120/minute", key_func=per_player_key)
async def survey_status(
    request: Request,
    survey_key: str,
    player: CurrentPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SurveyStatusResponse:
    """Whether ``player`` has already completed ``survey_key``."""
    _require_known(survey_key)
    existing = (
        await db.execute(
            select(SurveyCompletion.id).where(
                SurveyCompletion.player_id == player.id,
                SurveyCompletion.survey_key == survey_key,
            )
        )
    ).scalar_one_or_none()
    return SurveyStatusResponse(completed=existing is not None)


@router.post("/{survey_key}/response", response_model=SurveyStatusResponse)
@limiter.limit("20/minute", key_func=per_player_key)
async def submit_survey(
    request: Request,
    survey_key: str,
    body: Week1SubmitRequest,
    player: CurrentPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SurveyStatusResponse:
    """Record a response (idempotent per player) and mark the survey complete.

    The completion row and the de-identified response row are written together.
    A repeat submission is a no-op, and the unique completion constraint guards
    against double-recording if two tabs submit at once.
    """
    _require_known(survey_key)

    already = (
        await db.execute(
            select(SurveyCompletion.id).where(
                SurveyCompletion.player_id == player.id,
                SurveyCompletion.survey_key == survey_key,
            )
        )
    ).scalar_one_or_none()
    if already is not None:
        return SurveyStatusResponse(completed=True)

    # Auto-tag the caller's active leagues (same membership query as /me) so the
    # responses are segmentable per-league without the player typing anything.
    league_rows = (
        (
            await db.execute(
                select(LeagueMembership.league_id).where(
                    LeagueMembership.player_id == player.id,
                    LeagueMembership.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    league_ids = [str(lid) for lid in league_rows]

    db.add(
        SurveyResponse(
            survey_key=survey_key,
            league_ids=league_ids,
            answers=body.answers.model_dump(),
            contact_player_id=player.id if body.contact_ok else None,
        )
    )
    db.add(SurveyCompletion(player_id=player.id, survey_key=survey_key))
    try:
        await db.commit()
    except IntegrityError:
        # Lost a race with a concurrent submit; the other one recorded it.
        await db.rollback()
        return SurveyStatusResponse(completed=True)

    # Deliberately does NOT log answers or player id — feedback stays private.
    log.info("survey_submitted", survey_key=survey_key, contact_ok=body.contact_ok)
    return SurveyStatusResponse(completed=True)
