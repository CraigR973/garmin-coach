"""League join request management: list pending, approve, reject."""

import uuid
from datetime import datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.league_join_request import JoinRequestStatus, LeagueJoinRequest
from src.models.notification import ActionType
from src.models.profile import Profile
from src.rate_limit import limiter, per_player_key
from src.routers.leagues import (
    LeagueAdminDep,
    _active_member_count,
    _audit,
    _now,
    _upsert_membership,
)

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/leagues", tags=["leagues"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class JoinRequestResponse(BaseModel):
    id: str
    player_id: str
    display_name: str
    status: str
    requested_at: datetime
    decided_at: datetime | None
    decision_note: str | None


class DecideRequest(BaseModel):
    note: str | None = None


# ---------------------------------------------------------------------------
# GET /api/v1/leagues/{slug}/join-requests
# ---------------------------------------------------------------------------


@router.get("/{slug}/join-requests", response_model=list[JoinRequestResponse])
@limiter.limit("60/minute", key_func=per_player_key)
async def list_join_requests(
    request: Request,
    slug: str,
    admin_ctx: LeagueAdminDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[JoinRequestResponse]:
    _, league = admin_ctx
    result = await db.execute(
        select(LeagueJoinRequest, Profile)
        .join(Profile, Profile.id == LeagueJoinRequest.player_id)
        .where(
            LeagueJoinRequest.league_id == league.id,
            LeagueJoinRequest.status == JoinRequestStatus.pending,
        )
        .order_by(LeagueJoinRequest.requested_at)
    )
    return [
        JoinRequestResponse(
            id=str(row[0].id),
            player_id=str(row[0].player_id),
            display_name=row[1].display_name,
            status=row[0].status.value,
            requested_at=row[0].requested_at,
            decided_at=row[0].decided_at,
            decision_note=row[0].decision_note,
        )
        for row in result.all()
    ]


# ---------------------------------------------------------------------------
# POST /api/v1/leagues/{slug}/join-requests/{request_id}/approve
# ---------------------------------------------------------------------------


@router.post(
    "/{slug}/join-requests/{request_id}/approve",
    status_code=status.HTTP_204_NO_CONTENT,
)
@limiter.limit("60/hour", key_func=per_player_key)
async def approve_join_request(
    request: Request,
    slug: str,
    request_id: uuid.UUID,
    body: DecideRequest,
    admin_ctx: LeagueAdminDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    player, league = admin_ctx
    join_req = await _load_pending_request(request_id, league.id, db)

    member_count = await _active_member_count(league.id, db)
    if member_count >= league.max_members:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="LEAGUE_FULL: cannot approve, league is at capacity",
        )

    join_req.status = JoinRequestStatus.approved
    join_req.decided_at = _now()
    join_req.decided_by = player.id
    join_req.decision_note = body.note
    join_req.updated_at = _now()

    await _upsert_membership(league.id, join_req.player_id, db)
    db.add(
        _audit(
            player,
            ActionType.join_request_approved,
            "league_join_requests",
            league.id,
            {"request_id": str(request_id), "player_id": str(join_req.player_id)},
        )
    )
    await db.commit()
    log.info(
        "join request approved",
        request_id=str(request_id),
        league_id=str(league.id),
        player_id=str(join_req.player_id),
    )


# ---------------------------------------------------------------------------
# POST /api/v1/leagues/{slug}/join-requests/{request_id}/reject
# ---------------------------------------------------------------------------


@router.post(
    "/{slug}/join-requests/{request_id}/reject",
    status_code=status.HTTP_204_NO_CONTENT,
)
@limiter.limit("60/hour", key_func=per_player_key)
async def reject_join_request(
    request: Request,
    slug: str,
    request_id: uuid.UUID,
    body: DecideRequest,
    admin_ctx: LeagueAdminDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    player, league = admin_ctx
    join_req = await _load_pending_request(request_id, league.id, db)

    join_req.status = JoinRequestStatus.rejected
    join_req.decided_at = _now()
    join_req.decided_by = player.id
    join_req.decision_note = body.note
    join_req.updated_at = _now()

    db.add(
        _audit(
            player,
            ActionType.join_request_rejected,
            "league_join_requests",
            league.id,
            {"request_id": str(request_id), "player_id": str(join_req.player_id)},
        )
    )
    await db.commit()
    log.info(
        "join request rejected",
        request_id=str(request_id),
        league_id=str(league.id),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load_pending_request(
    request_id: uuid.UUID, league_id: uuid.UUID, db: AsyncSession
) -> LeagueJoinRequest:
    result = await db.execute(
        select(LeagueJoinRequest).where(
            LeagueJoinRequest.id == request_id,
            LeagueJoinRequest.league_id == league_id,
            LeagueJoinRequest.status == JoinRequestStatus.pending,
        )
    )
    req = result.scalar_one_or_none()
    if req is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pending join request not found",
        )
    return req
