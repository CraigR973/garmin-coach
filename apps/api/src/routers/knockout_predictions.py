"""Knockout prediction CRUD endpoints."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import CurrentPlayer
from src.database import get_db
from src.deps import shared_league_player_ids
from src.models.match import Match
from src.models.prediction import KnockoutPrediction
from src.models.profile import Profile
from src.rate_limit import limiter, per_player_key
from src.reveal_gate import match_prediction_revealed

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/knockout-predictions", tags=["knockout-predictions"])


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class KnockoutPredictionRequest(BaseModel):
    predicted_winner_id: uuid.UUID


class KnockoutPredictionResponse(BaseModel):
    id: str
    player_id: str
    match_id: str
    predicted_winner_id: str | None
    submitted_at: str | None
    update_count: int
    points_awarded: int | None
    updated_at: str


class MatchKnockoutPredictionItem(BaseModel):
    player_id: str
    player_name: str
    predicted_winner_id: str | None
    points_awarded: int | None


class MatchKnockoutPredictionsResponse(BaseModel):
    match_id: str
    predictions: list[MatchKnockoutPredictionItem]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_response(pred: KnockoutPrediction) -> KnockoutPredictionResponse:
    return KnockoutPredictionResponse(
        id=str(pred.id),
        player_id=str(pred.player_id),
        match_id=str(pred.match_id),
        predicted_winner_id=str(pred.predicted_winner_id) if pred.predicted_winner_id else None,
        submitted_at=pred.submitted_at.isoformat() + "Z" if pred.submitted_at else None,
        update_count=pred.update_count,
        points_awarded=pred.points_awarded,
        updated_at=pred.updated_at.isoformat() + "Z",
    )


async def _get_match_or_404(match_id: uuid.UUID, db: AsyncSession) -> Match:
    result = await db.execute(select(Match).where(Match.id == match_id, Match.deleted_at.is_(None)))
    match = result.scalar_one_or_none()
    if match is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Match not found")
    return match


# ---------------------------------------------------------------------------
# PUT /api/v1/knockout-predictions/{match_id}
# ---------------------------------------------------------------------------


@router.put("/{match_id}", response_model=KnockoutPredictionResponse)
@limiter.limit("60/hour", key_func=per_player_key)
async def upsert_knockout_prediction(
    request: Request,
    match_id: uuid.UUID,
    body: KnockoutPredictionRequest,
    player: CurrentPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnockoutPredictionResponse:
    match = await _get_match_or_404(match_id, db)

    # Validate winner is one of the match's teams when both are known
    if match.home_team_id is not None and match.away_team_id is not None:
        if body.predicted_winner_id not in (match.home_team_id, match.away_team_id):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="predicted_winner_id must be the home or away team",
            )

    now = _now()

    # Per-match lock (U22.1): a knockout prediction locks only at its own match's
    # kickoff. Sibling ties in the same stage are independent — one kicking off no
    # longer locks the rest of the round.
    if match.kickoff_utc <= now:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="PREDICTION_LOCKED")

    result = await db.execute(
        select(KnockoutPrediction).where(
            KnockoutPrediction.player_id == player.id,
            KnockoutPrediction.match_id == match_id,
        )
    )
    pred = result.scalar_one_or_none()

    if pred is None:
        pred = KnockoutPrediction(
            id=uuid.uuid4(),
            player_id=player.id,
            match_id=match_id,
            predicted_winner_id=body.predicted_winner_id,
            submitted_at=now,
            update_count=0,
        )
        db.add(pred)
    else:
        pred.predicted_winner_id = body.predicted_winner_id
        pred.update_count = pred.update_count + 1

    await db.commit()
    await db.refresh(pred)
    return _to_response(pred)


# ---------------------------------------------------------------------------
# GET /api/v1/knockout-predictions/me
# ---------------------------------------------------------------------------


@router.get("/me", response_model=list[KnockoutPredictionResponse])
async def my_knockout_predictions(
    player: CurrentPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[KnockoutPredictionResponse]:
    result = await db.execute(
        select(KnockoutPrediction).where(
            KnockoutPrediction.player_id == player.id,
        )
    )
    preds = result.scalars().all()
    return [_to_response(p) for p in preds]


# ---------------------------------------------------------------------------
# GET /api/v1/knockout-predictions/match/{match_id}
# ---------------------------------------------------------------------------


@router.get("/match/{match_id}", response_model=MatchKnockoutPredictionsResponse)
async def match_knockout_predictions(
    match_id: uuid.UUID,
    player: CurrentPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MatchKnockoutPredictionsResponse:
    match = await _get_match_or_404(match_id, db)

    # Per-match reveal gate (U22.1, shared gate U24): predictions for this match
    # stay hidden until the match itself locks at kickoff — symmetric with the
    # per-match write lock. A sibling tie kicking off does not reveal this one.
    if not match_prediction_revealed(match, _now()):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Predictions are hidden until the match is locked",
        )

    result = await db.execute(
        select(KnockoutPrediction, Profile)
        .join(Profile, KnockoutPrediction.player_id == Profile.id)
        .where(
            KnockoutPrediction.match_id == match_id,
            Profile.deleted_at.is_(None),
        )
    )
    rows = result.all()

    shared = await shared_league_player_ids(player.id, db)
    items = [
        MatchKnockoutPredictionItem(
            player_id=str(pred.player_id),
            player_name=prof.display_name,
            predicted_winner_id=str(pred.predicted_winner_id) if pred.predicted_winner_id else None,
            points_awarded=pred.points_awarded,
        )
        for pred, prof in rows
        if pred.player_id in shared
    ]
    return MatchKnockoutPredictionsResponse(match_id=str(match_id), predictions=items)
