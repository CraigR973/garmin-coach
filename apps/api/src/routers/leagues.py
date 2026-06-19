"""League management endpoints: create, read, update, delete, join, leave, discover."""

import re
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import CurrentPlayer, generate_join_code
from src.database import get_db
from src.models.league import League, LeaguePrivacy
from src.models.league_join_request import JoinRequestStatus, LeagueJoinRequest
from src.models.league_membership import LeagueMemberRole, LeagueMembership
from src.models.notification import ActionType, ActorType, AuditLog
from src.models.profile import Profile, SiteRole
from src.rate_limit import limiter, per_player_key
from src.services.notification_triggers import notify_member_joined

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/leagues", tags=["leagues"])


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Slug helpers
# ---------------------------------------------------------------------------


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower())
    return re.sub(r"-+", "-", s).strip("-")


async def _unique_slug(db: AsyncSession, name: str) -> str:
    base = _slugify(name)
    slug = base
    counter = 2
    while True:
        result = await db.execute(select(League.id).where(League.slug == slug))
        if result.scalar_one_or_none() is None:
            return slug
        slug = f"{base}-{counter}"
        counter += 1


# ---------------------------------------------------------------------------
# Shared dependencies
# ---------------------------------------------------------------------------


async def _resolve_league(slug: str, db: AsyncSession) -> League:
    result = await db.execute(
        select(League).where(League.slug == slug, League.deleted_at.is_(None))
    )
    league = result.scalar_one_or_none()
    if league is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="League not found")
    return league


async def _resolve_active_membership(
    league_id: uuid.UUID, player_id: uuid.UUID, db: AsyncSession
) -> LeagueMembership | None:
    result = await db.execute(
        select(LeagueMembership).where(
            LeagueMembership.league_id == league_id,
            LeagueMembership.player_id == player_id,
            LeagueMembership.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def _active_admin_count(league_id: uuid.UUID, db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count()).where(
            LeagueMembership.league_id == league_id,
            LeagueMembership.role == LeagueMemberRole.admin,
            LeagueMembership.deleted_at.is_(None),
        )
    )
    return result.scalar_one()


async def _active_member_count(league_id: uuid.UUID, db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count()).where(
            LeagueMembership.league_id == league_id,
            LeagueMembership.deleted_at.is_(None),
        )
    )
    return result.scalar_one()


def _is_superadmin(player: Profile) -> bool:
    return player.site_role is not None and player.site_role == SiteRole.superadmin


async def require_league_admin(
    slug: str,
    player: CurrentPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> tuple[Profile, League]:
    """Dependency: resolves league and verifies caller is league admin or site superadmin."""
    league = await _resolve_league(slug, db)
    if _is_superadmin(player):
        return player, league
    membership = await _resolve_active_membership(league.id, player.id, db)
    if membership is None or membership.role != LeagueMemberRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="League admin required")
    return player, league


async def require_league_member(
    slug: str,
    player: CurrentPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> tuple[Profile, League]:
    """Dependency: resolves league and verifies caller is an active member."""
    league = await _resolve_league(slug, db)
    if _is_superadmin(player):
        return player, league
    membership = await _resolve_active_membership(league.id, player.id, db)
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="League membership required"
        )
    return player, league


LeagueAdminDep = Annotated[tuple[Profile, League], Depends(require_league_admin)]
LeagueMemberDep = Annotated[tuple[Profile, League], Depends(require_league_member)]


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class CreateLeagueRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    privacy: LeaguePrivacy = LeaguePrivacy.private
    max_members: int = Field(default=15, ge=2, le=50)


class UpdateLeagueRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    description: str | None = None
    privacy: LeaguePrivacy | None = None
    max_members: int | None = Field(default=None, ge=2, le=50)


class LeagueResponse(BaseModel):
    id: str
    slug: str
    name: str
    description: str | None
    privacy: str
    max_members: int
    member_count: int
    created_by: str
    created_at: datetime
    join_code: str | None = None


class LeagueSummaryResponse(BaseModel):
    id: str
    slug: str
    name: str
    description: str | None
    privacy: str
    max_members: int
    member_count: int
    my_role: str | None


class DiscoverLeagueResponse(BaseModel):
    id: str
    slug: str
    name: str
    description: str | None
    max_members: int
    member_count: int
    privacy: str


class DiscoverResponse(BaseModel):
    leagues: list[DiscoverLeagueResponse]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# Audit helper
# ---------------------------------------------------------------------------


def _audit(
    actor: Profile,
    action: ActionType,
    target_table: str,
    target_id: uuid.UUID | None = None,
    changes: dict[str, Any] | None = None,
) -> AuditLog:
    actor_type = ActorType.admin if _is_superadmin(actor) else ActorType.player
    return AuditLog(
        actor_id=actor.id,
        actor_type=actor_type,
        action_type=action,
        target_table=target_table,
        target_id=target_id,
        changes=changes,
    )


# ---------------------------------------------------------------------------
# Privacy transition side effects
# ---------------------------------------------------------------------------


async def _cancel_pending_requests(league_id: uuid.UUID, db: AsyncSession) -> int:
    """Cancel all pending join requests for a league. Returns count cancelled."""
    result = await db.execute(
        select(LeagueJoinRequest).where(
            LeagueJoinRequest.league_id == league_id,
            LeagueJoinRequest.status == JoinRequestStatus.pending,
        )
    )
    requests = list(result.scalars().all())
    for req in requests:
        req.status = JoinRequestStatus.cancelled
        req.decided_at = _now()
    return len(requests)


async def _auto_approve_pending_requests(
    league_id: uuid.UUID, admin: Profile, db: AsyncSession
) -> int:
    """Auto-approve all pending join requests when switching to public_open.
    Creates/restores memberships for each requester. Returns count approved.
    """
    result = await db.execute(
        select(LeagueJoinRequest).where(
            LeagueJoinRequest.league_id == league_id,
            LeagueJoinRequest.status == JoinRequestStatus.pending,
        )
    )
    requests = list(result.scalars().all())
    for req in requests:
        req.status = JoinRequestStatus.approved
        req.decided_at = _now()
        req.decided_by = admin.id
        await _upsert_membership(league_id, req.player_id, db)
    return len(requests)


async def _upsert_membership(
    league_id: uuid.UUID,
    player_id: uuid.UUID,
    db: AsyncSession,
    *,
    role: LeagueMemberRole = LeagueMemberRole.player,
) -> LeagueMembership:
    """Create or restore a soft-deleted membership row."""
    result = await db.execute(
        select(LeagueMembership).where(
            LeagueMembership.league_id == league_id,
            LeagueMembership.player_id == player_id,
        )
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        # Restore soft-deleted row
        existing.deleted_at = None
        existing.joined_at = _now()
        existing.role = role
        existing.updated_at = _now()
        return existing
    membership = LeagueMembership(
        league_id=league_id,
        player_id=player_id,
        role=role,
        joined_at=_now(),
        created_at=_now(),
    )
    db.add(membership)
    return membership


# ---------------------------------------------------------------------------
# POST /api/v1/leagues  — create
# ---------------------------------------------------------------------------


@router.post("", response_model=LeagueResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("20/hour", key_func=per_player_key)
async def create_league(
    request: Request,
    body: CreateLeagueRequest,
    player: CurrentPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> LeagueResponse:
    slug = await _unique_slug(db, body.name)
    league = League(
        slug=slug,
        name=body.name,
        description=body.description,
        privacy=body.privacy,
        max_members=body.max_members,
        created_by=player.id,
        created_at=_now(),
        join_code=generate_join_code(),
    )
    db.add(league)
    await db.flush()  # populate league.id before FK reference

    membership = LeagueMembership(
        league_id=league.id,
        player_id=player.id,
        role=LeagueMemberRole.admin,
        joined_at=_now(),
        created_at=_now(),
    )
    db.add(membership)

    db.add(
        _audit(
            player,
            ActionType.league_created,
            "leagues",
            league.id,
            {"name": body.name, "privacy": body.privacy.value},
        )
    )

    await db.commit()
    await db.refresh(league)

    log.info("league created", league_id=str(league.id), slug=slug, player_id=str(player.id))
    return LeagueResponse(
        id=str(league.id),
        slug=league.slug,
        name=league.name,
        description=league.description,
        privacy=league.privacy.value,
        max_members=league.max_members,
        member_count=1,
        created_by=str(league.created_by),
        created_at=league.created_at,
        join_code=league.join_code,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/leagues/mine
# ---------------------------------------------------------------------------


@router.get("/mine", response_model=list[LeagueSummaryResponse])
@limiter.limit("120/minute", key_func=per_player_key)
async def list_my_leagues(
    request: Request,
    player: CurrentPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[LeagueSummaryResponse]:
    result = await db.execute(
        select(League, LeagueMembership, func.count().label("member_count"))
        .join(LeagueMembership, LeagueMembership.league_id == League.id)
        .where(
            LeagueMembership.player_id == player.id,
            LeagueMembership.deleted_at.is_(None),
            League.deleted_at.is_(None),
        )
        .outerjoin(
            LeagueMembership.__table__.alias("all_members"),
            (LeagueMembership.__table__.alias("all_members").c.league_id == League.id)
            & (LeagueMembership.__table__.alias("all_members").c.deleted_at.is_(None)),
        )
        .group_by(League.id, LeagueMembership.id)
        .order_by(League.name)
    )
    rows = list(result.all())
    # Re-query member counts separately to keep the join simple
    out: list[LeagueSummaryResponse] = []
    for row in rows:
        league: League = row[0]
        membership: LeagueMembership = row[1]
        count = await _active_member_count(league.id, db)
        out.append(
            LeagueSummaryResponse(
                id=str(league.id),
                slug=league.slug,
                name=league.name,
                description=league.description,
                privacy=league.privacy.value,
                max_members=league.max_members,
                member_count=count,
                my_role=membership.role.value,
            )
        )
    return out


# ---------------------------------------------------------------------------
# GET /api/v1/leagues/discover
# ---------------------------------------------------------------------------


@router.get("/discover", response_model=DiscoverResponse)
@limiter.limit("60/minute", key_func=per_player_key)
async def discover_leagues(
    request: Request,
    player: CurrentPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = 1,
    page_size: int = 20,
) -> DiscoverResponse:
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 50:
        page_size = 20

    # IDs of leagues caller is already in
    member_sub = (
        select(LeagueMembership.league_id)
        .where(
            LeagueMembership.player_id == player.id,
            LeagueMembership.deleted_at.is_(None),
        )
        .scalar_subquery()
    )
    member_count_sub = (
        select(func.count())
        .where(
            LeagueMembership.league_id == League.id,
            LeagueMembership.deleted_at.is_(None),
        )
        .correlate(League)
        .scalar_subquery()
    )

    base_q = select(League, member_count_sub.label("member_count")).where(
        League.privacy.in_([LeaguePrivacy.public_request, LeaguePrivacy.public_open]),
        League.deleted_at.is_(None),
        League.id.not_in(member_sub),
    )
    total_result = await db.execute(select(func.count()).select_from(base_q.subquery()))
    total = total_result.scalar_one()

    rows_result = await db.execute(
        base_q.order_by(member_count_sub.desc(), League.name.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = list(rows_result.all())

    leagues = [
        DiscoverLeagueResponse(
            id=str(row[0].id),
            slug=row[0].slug,
            name=row[0].name,
            description=row[0].description,
            max_members=row[0].max_members,
            member_count=row[1],
            privacy=(
                row[0].privacy.value if hasattr(row[0].privacy, "value") else str(row[0].privacy)
            ),
        )
        for row in rows
    ]
    return DiscoverResponse(leagues=leagues, total=total, page=page, page_size=page_size)


# ---------------------------------------------------------------------------
# GET /api/v1/leagues/by-code/{code}  — public, no auth required
# ---------------------------------------------------------------------------


class LeagueByCodeResponse(BaseModel):
    name: str
    member_count: int
    max_members: int
    privacy: str


@router.get("/by-code/{code}", response_model=LeagueByCodeResponse)
@limiter.limit("60/minute")
async def get_league_by_code(
    request: Request,
    code: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> LeagueByCodeResponse:
    result = await db.execute(
        select(League).where(
            League.join_code == code.upper(),
            League.deleted_at.is_(None),
        )
    )
    league = result.scalar_one_or_none()
    if league is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="League not found")
    count = await _active_member_count(league.id, db)
    return LeagueByCodeResponse(
        name=league.name,
        member_count=count,
        max_members=league.max_members,
        privacy=league.privacy.value,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/leagues/{slug}
# ---------------------------------------------------------------------------


class MemberInfo(BaseModel):
    id: str
    display_name: str
    role: str
    joined_at: datetime
    avatar_url: str | None = None


class LeagueDetailResponse(BaseModel):
    id: str
    slug: str
    name: str
    description: str | None
    privacy: str
    max_members: int
    member_count: int
    created_by: str
    created_at: datetime
    join_code: str | None = None
    members: list[MemberInfo] | None  # None when caller is not a member


@router.get("/{slug}", response_model=LeagueDetailResponse)
@limiter.limit("120/minute", key_func=per_player_key)
async def get_league(
    request: Request,
    slug: str,
    player: CurrentPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> LeagueDetailResponse:
    league = await _resolve_league(slug, db)

    # Check if caller is a member (or superadmin)
    is_member = _is_superadmin(player)
    if not is_member:
        m = await _resolve_active_membership(league.id, player.id, db)
        is_member = m is not None

    # Private leagues are not enumerable by non-members — return 404 to avoid
    # confirming the league's existence.
    if league.privacy == LeaguePrivacy.private and not is_member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="League not found")

    member_count = await _active_member_count(league.id, db)

    members_out: list[MemberInfo] | None = None
    if is_member:
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
        members_out = [
            MemberInfo(
                id=str(row[1].id),
                display_name=row[0].display_name_override or row[1].display_name,
                role=row[0].role.value,
                joined_at=row[0].joined_at,
                avatar_url=row[1].avatar_url,
            )
            for row in result.all()
        ]

    return LeagueDetailResponse(
        id=str(league.id),
        slug=league.slug,
        name=league.name,
        description=league.description,
        privacy=league.privacy.value,
        max_members=league.max_members,
        member_count=member_count,
        created_by=str(league.created_by),
        created_at=league.created_at,
        join_code=league.join_code if is_member else None,
        members=members_out,
    )


# ---------------------------------------------------------------------------
# PATCH /api/v1/leagues/{slug}  — edit settings
# ---------------------------------------------------------------------------


@router.patch("/{slug}", response_model=LeagueResponse)
@limiter.limit("30/hour", key_func=per_player_key)
async def update_league(
    request: Request,
    slug: str,
    body: UpdateLeagueRequest,
    admin_ctx: LeagueAdminDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> LeagueResponse:
    player, league = admin_ctx

    changes: dict[str, Any] = {}

    if body.name is not None and body.name != league.name:
        changes["name"] = {"from": league.name, "to": body.name}
        league.name = body.name

    if body.description is not None and body.description != league.description:
        changes["description"] = {"from": league.description, "to": body.description}
        league.description = body.description

    if body.max_members is not None and body.max_members != league.max_members:
        if body.max_members < await _active_member_count(league.id, db):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="max_members cannot be lower than current member count",
            )
        changes["max_members"] = {"from": league.max_members, "to": body.max_members}
        league.max_members = body.max_members

    privacy_changed = body.privacy is not None and body.privacy != league.privacy
    if privacy_changed:
        old_privacy = league.privacy
        new_privacy = body.privacy
        assert new_privacy is not None

        # Transition side effects
        if new_privacy == LeaguePrivacy.private:
            # Cancel all pending join requests
            await _cancel_pending_requests(league.id, db)
        elif (
            old_privacy == LeaguePrivacy.public_request and new_privacy == LeaguePrivacy.public_open
        ):
            # Auto-approve pending requests
            member_count = await _active_member_count(league.id, db)
            if member_count < league.max_members:
                await _auto_approve_pending_requests(league.id, player, db)

        changes["privacy"] = {"from": old_privacy.value, "to": new_privacy.value}
        league.privacy = new_privacy

        db.add(_audit(player, ActionType.league_privacy_changed, "leagues", league.id, changes))
    elif changes:
        db.add(_audit(player, ActionType.league_updated, "leagues", league.id, changes))

    league.updated_at = _now()
    await db.commit()
    await db.refresh(league)

    member_count = await _active_member_count(league.id, db)
    return LeagueResponse(
        id=str(league.id),
        slug=league.slug,
        name=league.name,
        description=league.description,
        privacy=league.privacy.value,
        max_members=league.max_members,
        member_count=member_count,
        created_by=str(league.created_by),
        created_at=league.created_at,
        join_code=league.join_code,
    )


# ---------------------------------------------------------------------------
# DELETE /api/v1/leagues/{slug}  — soft delete
# ---------------------------------------------------------------------------


class DeleteLeagueRequest(BaseModel):
    confirm_name: str = Field(description="Caller must type the league name to confirm deletion")


@router.delete("/{slug}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/hour", key_func=per_player_key)
async def delete_league(
    request: Request,
    slug: str,
    body: DeleteLeagueRequest,
    admin_ctx: LeagueAdminDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    player, league = admin_ctx
    if body.confirm_name != league.name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="confirm_name does not match league name",
        )
    league.deleted_at = _now()
    league.updated_at = _now()
    db.add(_audit(player, ActionType.league_deleted, "leagues", league.id, {"name": league.name}))
    await db.commit()
    log.info("league deleted", league_id=str(league.id), slug=slug, player_id=str(player.id))


# ---------------------------------------------------------------------------
# POST /api/v1/leagues/{slug}/join
# ---------------------------------------------------------------------------


class JoinResponse(BaseModel):
    status: str  # "joined" or "pending"


@router.post("/{slug}/join", response_model=JoinResponse, status_code=status.HTTP_200_OK)
@limiter.limit("30/hour", key_func=per_player_key)
async def join_league(
    request: Request,
    slug: str,
    player: CurrentPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JoinResponse:
    league = await _resolve_league(slug, db)

    if league.privacy == LeaguePrivacy.private:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="PRIVATE_LEAGUE: join via invite only",
        )

    # Already a member?
    existing = await _resolve_active_membership(league.id, player.id, db)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="ALREADY_MEMBER",
        )

    member_count = await _active_member_count(league.id, db)
    if member_count >= league.max_members:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="LEAGUE_FULL",
        )

    if league.privacy == LeaguePrivacy.public_open:
        await _upsert_membership(league.id, player.id, db)
        db.add(_audit(player, ActionType.member_joined, "league_memberships", league.id))
        await notify_member_joined(db, player.display_name, league.name)
        await db.commit()
        log.info("league joined", league_id=str(league.id), player_id=str(player.id))
        return JoinResponse(status="joined")

    # public_request: create or reuse a pending join request
    existing_req_result = await db.execute(
        select(LeagueJoinRequest).where(
            LeagueJoinRequest.league_id == league.id,
            LeagueJoinRequest.player_id == player.id,
            LeagueJoinRequest.status == JoinRequestStatus.pending,
        )
    )
    if existing_req_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="JOIN_REQUEST_PENDING",
        )
    join_req = LeagueJoinRequest(
        league_id=league.id,
        player_id=player.id,
        status=JoinRequestStatus.pending,
        requested_at=_now(),
        created_at=_now(),
    )
    db.add(join_req)
    db.add(_audit(player, ActionType.join_request_created, "league_join_requests", league.id))
    await db.commit()
    log.info("join request created", league_id=str(league.id), player_id=str(player.id))
    return JoinResponse(status="pending")


# ---------------------------------------------------------------------------
# DELETE /api/v1/leagues/{slug}/membership  — leave
# ---------------------------------------------------------------------------


@router.delete("/{slug}/membership", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/hour", key_func=per_player_key)
async def leave_league(
    request: Request,
    slug: str,
    player: CurrentPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    league = await _resolve_league(slug, db)
    membership = await _resolve_active_membership(league.id, player.id, db)
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not a member of this league",
        )

    # Last-admin protection
    if membership.role == LeagueMemberRole.admin:
        admin_count = await _active_admin_count(league.id, db)
        if admin_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="LAST_ADMIN: promote another member to admin before leaving",
            )

    membership.deleted_at = _now()
    membership.updated_at = _now()
    db.add(_audit(player, ActionType.member_left, "league_memberships", league.id))
    await db.commit()
    log.info("left league", league_id=str(league.id), player_id=str(player.id))
