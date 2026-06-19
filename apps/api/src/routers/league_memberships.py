"""League membership management: list, promote, demote, remove, display-name, invites, PIN reset."""

import uuid
from datetime import datetime, timedelta
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import CurrentPlayer, generate_join_code, generate_opaque_token, hash_pin
from src.database import get_db
from src.models.invite import Invite
from src.models.league import League
from src.models.league_membership import LeagueMemberRole, LeagueMembership
from src.models.notification import ActionType
from src.models.profile import Profile
from src.rate_limit import limiter, per_player_key
from src.routers.leagues import (
    LeagueAdminDep,
    LeagueMemberDep,
    MemberInfo,
    _active_admin_count,
    _active_member_count,
    _audit,
    _now,
    _resolve_active_membership,
    _upsert_membership,
)
from src.services.notification_triggers import notify_member_joined

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/leagues", tags=["leagues"])


# ---------------------------------------------------------------------------
# POST /api/v1/leagues/claim-invite
# Authenticated player claims an invite token to join a private league.
# Must be registered before /{slug} routes to avoid slug-capture.
# ---------------------------------------------------------------------------


class ClaimInviteBody(BaseModel):
    token: str


class ClaimInviteResponse(BaseModel):
    league_slug: str
    league_name: str


@router.post("/claim-invite", response_model=ClaimInviteResponse, status_code=status.HTTP_200_OK)
@limiter.limit("10/hour", key_func=per_player_key)
async def claim_invite_authenticated(
    request: Request,
    body: ClaimInviteBody,
    player: CurrentPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ClaimInviteResponse:
    invite_result = await db.execute(select(Invite).where(Invite.token == body.token))
    invite = invite_result.scalar_one_or_none()

    if invite is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid invite token")
    if not invite.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invite has been revoked"
        )
    if invite.claimed_by is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invite already used")
    if invite.expires_at is not None and invite.expires_at < _now():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invite has expired")

    league_result = await db.execute(select(League).where(League.id == invite.league_id))
    league = league_result.scalar_one_or_none()
    if league is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="League not found")

    existing = await _resolve_active_membership(league.id, player.id, db)
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="ALREADY_MEMBER")

    if await _active_member_count(league.id, db) >= league.max_members:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="LEAGUE_FULL")

    await _upsert_membership(league.id, player.id, db)
    db.add(_audit(player, ActionType.member_joined, "league_memberships", league.id))
    await notify_member_joined(db, player.display_name, league.name)

    invite.claimed_by = player.id
    invite.claimed_at = _now()
    invite.is_active = False

    await db.commit()
    log.info("invite claimed", league_id=str(league.id), player_id=str(player.id))
    return ClaimInviteResponse(league_slug=league.slug, league_name=league.name)


# ---------------------------------------------------------------------------
# POST /api/v1/leagues/join-by-code
# Authenticated player joins a league using its reusable join code.
# Must be registered before /{slug} routes to avoid slug-capture.
# ---------------------------------------------------------------------------


class JoinByCodeBody(BaseModel):
    code: str


class JoinByCodeResponse(BaseModel):
    league_slug: str
    league_name: str


@router.post("/join-by-code", response_model=JoinByCodeResponse, status_code=status.HTTP_200_OK)
@limiter.limit("20/hour", key_func=per_player_key)
async def join_league_by_code(
    request: Request,
    body: JoinByCodeBody,
    player: CurrentPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JoinByCodeResponse:
    result = await db.execute(
        select(League).where(
            League.join_code == body.code.upper(),
            League.deleted_at.is_(None),
        )
    )
    league = result.scalar_one_or_none()
    if league is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid join code")

    existing = await _resolve_active_membership(league.id, player.id, db)
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="ALREADY_MEMBER")

    if await _active_member_count(league.id, db) >= league.max_members:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="LEAGUE_FULL")

    await _upsert_membership(league.id, player.id, db)
    db.add(_audit(player, ActionType.member_joined, "league_memberships", league.id))
    await notify_member_joined(db, player.display_name, league.name)
    await db.commit()
    log.info("joined by code", league_id=str(league.id), player_id=str(player.id))
    return JoinByCodeResponse(league_slug=league.slug, league_name=league.name)


# ---------------------------------------------------------------------------
# GET /api/v1/leagues/{slug}/members
# ---------------------------------------------------------------------------


@router.get("/{slug}/members", response_model=list[MemberInfo])
@limiter.limit("120/minute", key_func=per_player_key)
async def list_members(
    request: Request,
    slug: str,
    member_ctx: LeagueMemberDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[MemberInfo]:
    _, league = member_ctx
    result = await db.execute(
        select(LeagueMembership, Profile)
        .join(Profile, Profile.id == LeagueMembership.player_id)
        .where(
            LeagueMembership.league_id == league.id,
            LeagueMembership.deleted_at.is_(None),
            Profile.deleted_at.is_(None),
        )
        .order_by(LeagueMembership.joined_at)
    )
    return [
        MemberInfo(
            id=str(row[1].id),
            display_name=row[0].display_name_override or row[1].display_name,
            role=row[0].role.value,
            joined_at=row[0].joined_at,
            avatar_url=row[1].avatar_url,
        )
        for row in result.all()
    ]


# ---------------------------------------------------------------------------
# POST /api/v1/leagues/{slug}/members/{player_id}/promote
# ---------------------------------------------------------------------------


@router.post("/{slug}/members/{target_player_id}/promote", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/hour", key_func=per_player_key)
async def promote_member(
    request: Request,
    slug: str,
    target_player_id: uuid.UUID,
    admin_ctx: LeagueAdminDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    player, league = admin_ctx
    membership = await _resolve_active_membership(league.id, target_player_id, db)
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    if membership.role == LeagueMemberRole.admin:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already an admin")
    membership.role = LeagueMemberRole.admin
    membership.updated_at = _now()
    db.add(
        _audit(
            player,
            ActionType.member_promoted,
            "league_memberships",
            league.id,
            {"player_id": str(target_player_id)},
        )
    )
    await db.commit()
    log.info("member promoted", league_id=str(league.id), target=str(target_player_id))


# ---------------------------------------------------------------------------
# POST /api/v1/leagues/{slug}/members/{player_id}/demote
# ---------------------------------------------------------------------------


@router.post("/{slug}/members/{target_player_id}/demote", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/hour", key_func=per_player_key)
async def demote_member(
    request: Request,
    slug: str,
    target_player_id: uuid.UUID,
    admin_ctx: LeagueAdminDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    player, league = admin_ctx
    membership = await _resolve_active_membership(league.id, target_player_id, db)
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    if membership.role != LeagueMemberRole.admin:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Not an admin")

    admin_count = await _active_admin_count(league.id, db)
    if admin_count <= 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="LAST_ADMIN: cannot demote the last admin",
        )
    membership.role = LeagueMemberRole.player
    membership.updated_at = _now()
    db.add(
        _audit(
            player,
            ActionType.member_demoted,
            "league_memberships",
            league.id,
            {"player_id": str(target_player_id)},
        )
    )
    await db.commit()
    log.info("member demoted", league_id=str(league.id), target=str(target_player_id))


# ---------------------------------------------------------------------------
# DELETE /api/v1/leagues/{slug}/members/{player_id}
# ---------------------------------------------------------------------------


@router.delete("/{slug}/members/{target_player_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/hour", key_func=per_player_key)
async def remove_member(
    request: Request,
    slug: str,
    target_player_id: uuid.UUID,
    admin_ctx: LeagueAdminDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    player, league = admin_ctx
    membership = await _resolve_active_membership(league.id, target_player_id, db)
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    if membership.role == LeagueMemberRole.admin:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Demote the member from admin before removing",
        )
    membership.deleted_at = _now()
    membership.updated_at = _now()
    db.add(
        _audit(
            player,
            ActionType.member_removed,
            "league_memberships",
            league.id,
            {"player_id": str(target_player_id)},
        )
    )
    await db.commit()
    log.info("member removed", league_id=str(league.id), target=str(target_player_id))


# ---------------------------------------------------------------------------
# PUT /api/v1/leagues/{slug}/members/me/display-name
# ---------------------------------------------------------------------------


class DisplayNameRequest(BaseModel):
    display_name_override: str | None = Field(default=None, max_length=100)


@router.put("/{slug}/members/me/display-name", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/hour", key_func=per_player_key)
async def set_my_display_name(
    request: Request,
    slug: str,
    body: DisplayNameRequest,
    member_ctx: LeagueMemberDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    player, league = member_ctx
    membership = await _resolve_active_membership(league.id, player.id, db)
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Membership not found")
    membership.display_name_override = body.display_name_override
    membership.updated_at = _now()
    await db.commit()


# ---------------------------------------------------------------------------
# POST /api/v1/leagues/{slug}/invites
# ---------------------------------------------------------------------------


class CreateLeagueInviteRequest(BaseModel):
    display_name_hint: str | None = None
    expires_in_days: int | None = Field(default=7, ge=1, le=30)


class LeagueInviteResponse(BaseModel):
    id: str
    token: str
    display_name_hint: str | None
    created_by: str
    claimed_by: str | None
    claimed_at: datetime | None
    expires_at: datetime | None
    is_active: bool
    created_at: datetime
    league_id: str


@router.post(
    "/{slug}/invites",
    response_model=LeagueInviteResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("30/hour", key_func=per_player_key)
async def create_league_invite(
    request: Request,
    slug: str,
    body: CreateLeagueInviteRequest,
    admin_ctx: LeagueAdminDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> LeagueInviteResponse:
    player, league = admin_ctx
    expires_at = None
    if body.expires_in_days is not None:
        expires_at = _now() + timedelta(days=body.expires_in_days)

    invite = Invite(
        token=generate_opaque_token(),
        display_name_hint=body.display_name_hint,
        league_id=league.id,
        created_by=player.id,
        expires_at=expires_at,
        is_active=True,
        created_at=_now(),
    )
    db.add(invite)
    db.add(
        _audit(
            player,
            ActionType.league_invite_created,
            "invites",
            league.id,
            {"league_slug": slug},
        )
    )
    await db.commit()
    await db.refresh(invite)

    log.info("league invite created", invite_id=str(invite.id), league_id=str(league.id))
    return _invite_response(invite)


# ---------------------------------------------------------------------------
# GET /api/v1/leagues/{slug}/invites
# ---------------------------------------------------------------------------


@router.get("/{slug}/invites", response_model=list[LeagueInviteResponse])
@limiter.limit("60/minute", key_func=per_player_key)
async def list_league_invites(
    request: Request,
    slug: str,
    admin_ctx: LeagueAdminDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[LeagueInviteResponse]:
    _, league = admin_ctx
    result = await db.execute(
        select(Invite)
        .where(Invite.league_id == league.id, Invite.is_active.is_(True))
        .order_by(Invite.created_at.desc())
    )
    return [_invite_response(i) for i in result.scalars().all()]


# ---------------------------------------------------------------------------
# DELETE /api/v1/leagues/{slug}/invites/{invite_id}
# ---------------------------------------------------------------------------


@router.delete("/{slug}/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/hour", key_func=per_player_key)
async def revoke_league_invite(
    request: Request,
    slug: str,
    invite_id: uuid.UUID,
    admin_ctx: LeagueAdminDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    player, league = admin_ctx
    result = await db.execute(
        select(Invite).where(Invite.id == invite_id, Invite.league_id == league.id)
    )
    invite = result.scalar_one_or_none()
    if invite is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")
    invite.is_active = False
    db.add(
        _audit(
            player,
            ActionType.league_invite_revoked,
            "invites",
            invite.id,
            {"league_slug": slug},
        )
    )
    await db.commit()
    log.info("league invite revoked", invite_id=str(invite_id), league_id=str(league.id))


# ---------------------------------------------------------------------------
# POST /api/v1/leagues/{slug}/members/{player_id}/reset-pin
# ---------------------------------------------------------------------------


class LeagueResetPinResponse(BaseModel):
    temp_pin: str


@router.post(
    "/{slug}/members/{target_player_id}/reset-pin",
    response_model=LeagueResetPinResponse,
)
@limiter.limit("10/hour", key_func=per_player_key)
async def reset_member_pin(
    request: Request,
    slug: str,
    target_player_id: uuid.UUID,
    admin_ctx: LeagueAdminDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> LeagueResetPinResponse:
    player, league = admin_ctx

    # Confirm target is an active member
    membership = await _resolve_active_membership(league.id, target_player_id, db)
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")

    # Load the profile
    result = await db.execute(
        select(Profile).where(
            Profile.id == target_player_id,
            Profile.deleted_at.is_(None),
        )
    )
    target = result.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")

    import secrets as _secrets  # noqa: PLC0415

    temp_pin = _secrets.randbelow(9000) + 1000  # 1000–9999
    target.pin_hash = hash_pin(str(temp_pin))
    target.updated_at = _now()
    db.add(
        _audit(
            player,
            ActionType.league_member_pin_reset,
            "profiles",
            target_player_id,
            {"league_slug": slug},
        )
    )
    await db.commit()
    log.info("pin reset by league admin", target=str(target_player_id), league=slug)
    return LeagueResetPinResponse(temp_pin=str(temp_pin))


# ---------------------------------------------------------------------------
# POST /api/v1/leagues/{slug}/join-code/rotate  — admin: regenerate join code
# ---------------------------------------------------------------------------


class RotateJoinCodeResponse(BaseModel):
    join_code: str


@router.post(
    "/{slug}/join-code/rotate",
    response_model=RotateJoinCodeResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit("10/hour", key_func=per_player_key)
async def rotate_join_code(
    request: Request,
    slug: str,
    admin_ctx: LeagueAdminDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RotateJoinCodeResponse:
    player, league = admin_ctx
    new_code = generate_join_code()
    league.join_code = new_code
    league.updated_at = _now()
    db.add(_audit(player, ActionType.league_join_code_rotated, "leagues", league.id))
    await db.commit()
    log.info("join code rotated", league_id=str(league.id))
    return RotateJoinCodeResponse(join_code=new_code)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _invite_response(invite: Invite) -> LeagueInviteResponse:
    return LeagueInviteResponse(
        id=str(invite.id),
        token=invite.token,
        display_name_hint=invite.display_name_hint,
        created_by=str(invite.created_by),
        claimed_by=str(invite.claimed_by) if invite.claimed_by else None,
        claimed_at=invite.claimed_at,
        expires_at=invite.expires_at,
        is_active=invite.is_active,
        created_at=invite.created_at,
        league_id=str(invite.league_id),
    )
