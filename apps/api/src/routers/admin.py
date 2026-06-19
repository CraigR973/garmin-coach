"""Admin endpoints: invite management, player management, standings override, result entry."""

import secrets
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import AdminPlayer, generate_join_code, hash_pin
from src.config import settings
from src.database import get_db
from src.models.group import Group
from src.models.invite import Invite
from src.models.league import League
from src.models.league_membership import LeagueMembership
from src.models.match import Match, MatchStatus, ResultSource
from src.models.notification import ActionType, ActorType, AuditLog
from src.models.prediction import (
    KnockoutPrediction,
    LeaderboardTiebreakOverride,
    Prediction,
)
from src.models.profile import Profile
from src.models.team import TournamentStage
from src.rate_limit import limiter, per_player_key
from src.services.backup import BackupInfo, create_backup, list_backups, resolve_backup_path
from src.services.football_data import FDMatch, FootballDataClient, FootballDataError
from src.services.knockout_advancement import (
    AlreadyAdvancedError,
    GroupStageIncompleteError,
    MissingKickoffsError,
    advance_to_r32,
    sync_knockout_bracket,
)
from src.services.leaderboard import recompute_leaderboard_snapshot
from src.services.notification_triggers import (
    MatchUpdate,
    notify_kickoff_changed,
    notify_match_postponed,
)
from src.services.result_sync import sync_results

FdFetcher = Callable[[], Awaitable[list[FDMatch]]]

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class InviteResponse(BaseModel):
    id: str
    token: str
    display_name_hint: str | None
    created_by: str
    claimed_by: str | None
    claimed_at: datetime | None
    expires_at: datetime | None
    is_active: bool
    created_at: datetime


class ResetPinResponse(BaseModel):
    temp_pin: str


class OverrideStandingsRequest(BaseModel):
    positions: list[str]  # ordered list of team codes, position 1 first


class TiebreakOverrideRequest(BaseModel):
    # Lower sorts higher (rank 1 first). Only the final ORDER BY key, so it only
    # ever decides a genuine all-axis tie (U38.4).
    manual_order: int
    reason: str | None = Field(default=None, max_length=500)


class TiebreakOverrideResponse(BaseModel):
    league_slug: str
    player_id: str
    player_name: str
    manual_order: int
    reason: str | None


class AdminPlayerResponse(BaseModel):
    id: str
    display_name: str
    first_name: str
    last_name: str
    email: str
    role: str
    timezone: str
    is_deleted: bool
    created_at: datetime
    failed_login_count: int
    locked_until: datetime | None


class ResultRequest(BaseModel):
    actual_home_score: int = Field(ge=0)
    actual_away_score: int = Field(ge=0)
    extra_time: bool = False
    penalties: bool = False
    penalty_winner_id: str | None = None  # UUID string for the winning team


class ResultResponse(BaseModel):
    match_id: str
    actual_home_score: int
    actual_away_score: int
    extra_time: bool
    penalties: bool
    penalty_winner_id: str | None
    result_source: str
    result_entered_at: datetime | None
    result_entered_by: str | None
    status: str


_VALID_RESULT_STATUSES = {MatchStatus.locked, MatchStatus.live, MatchStatus.completed}

_SYNC_ACTION_TYPES = {
    ActionType.result_auto_fetched,
    ActionType.sync_failed,
    ActionType.kickoff_changed,
    ActionType.sync_triggered,
}


class AuditEntryResponse(BaseModel):
    id: str
    action_type: str
    timestamp: datetime
    changes: dict[str, Any] | None


class SyncStatusResponse(BaseModel):
    last_sync_at: datetime | None
    last_sync_action: str | None
    next_run_at: datetime | None
    recent_errors: list[AuditEntryResponse]


class AdminMatchResultResponse(BaseModel):
    match_id: str
    match_number: int
    status: str
    # Knockout matches (stage != "group") may need a penalty winner; the admin
    # result form uses ``stage`` + the team ids below to offer that choice.
    stage: str | None = None
    kickoff_utc: datetime
    home_team: str | None
    away_team: str | None
    home_team_id: str | None = None
    away_team_id: str | None = None
    actual_home_score: int | None
    actual_away_score: int | None
    extra_time: bool
    penalties: bool
    result_source: str | None
    result_entered_at: datetime | None


class UpcomingLockResponse(BaseModel):
    match_id: str
    match_number: int
    kickoff_utc: datetime
    home_team: str | None
    away_team: str | None
    minutes_until_lock: int


class DashboardAuditEntry(BaseModel):
    id: str
    action_type: str
    actor_type: str
    timestamp: datetime
    target_table: str


class AdminDashboardResponse(BaseModel):
    active_players: int
    upcoming_locks: list[UpcomingLockResponse]
    pending_result_matches: list[AdminMatchResultResponse]
    recent_audit: list[DashboardAuditEntry]
    sync_status: SyncStatusResponse


class RescheduleRequest(BaseModel):
    kickoff_utc: datetime


class PostponeRequest(BaseModel):
    reason: str


class MatchAdminResponse(BaseModel):
    id: str
    match_number: int
    status: str
    kickoff_utc: datetime
    original_kickoff_utc: datetime | None
    locked_at: datetime | None
    postponed_reason: str | None


class KnockoutAdvanceRequest(BaseModel):
    # Phase 7.1 only supports advancing out of the group stage. Later
    # phases will widen this to {"r32", "r16", "qf", "sf"}.
    from_stage: Literal["group"] = "group"


class KnockoutMatchResponse(BaseModel):
    id: str
    match_number: int
    stage: str
    kickoff_utc: datetime
    home_team_id: str
    away_team_id: str
    home_team_placeholder: str
    away_team_placeholder: str
    football_data_match_id: int | None


class KnockoutAdvanceResponse(BaseModel):
    to_stage: str
    matches: list[KnockoutMatchResponse]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


class AdminLeagueSummary(BaseModel):
    slug: str
    name: str
    privacy: str
    member_count: int
    created_at: datetime
    join_code: str | None


@router.get("/leagues", response_model=list[AdminLeagueSummary])
async def list_all_leagues(
    admin: AdminPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[AdminLeagueSummary]:
    """List all non-deleted leagues with their member counts. Superadmin only."""
    league_rows = (
        (await db.execute(select(League).where(League.deleted_at.is_(None)).order_by(League.name)))
        .scalars()
        .all()
    )

    if not league_rows:
        return []

    league_ids = [lg.id for lg in league_rows]
    count_rows = (
        await db.execute(
            select(LeagueMembership.league_id, func.count().label("member_count"))
            .where(
                LeagueMembership.league_id.in_(league_ids),
                LeagueMembership.deleted_at.is_(None),
            )
            .group_by(LeagueMembership.league_id)
        )
    ).all()
    member_counts = {row.league_id: row.member_count for row in count_rows}

    return [
        AdminLeagueSummary(
            slug=lg.slug,
            name=lg.name,
            privacy=lg.privacy.value if hasattr(lg.privacy, "value") else str(lg.privacy),
            member_count=member_counts.get(lg.id, 0),
            created_at=lg.created_at,
            join_code=lg.join_code,
        )
        for lg in league_rows
    ]


class AdminRotateJoinCodeResponse(BaseModel):
    join_code: str


@router.post(
    "/leagues/{slug}/rotate-join-code",
    response_model=AdminRotateJoinCodeResponse,
    status_code=status.HTTP_200_OK,
)
async def admin_rotate_join_code(
    slug: str,
    admin: AdminPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AdminRotateJoinCodeResponse:
    """Superadmin: regenerate the join code for any league."""
    result = await db.execute(
        select(League).where(League.slug == slug, League.deleted_at.is_(None))
    )
    league = result.scalar_one_or_none()
    if league is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="League not found")
    new_code = generate_join_code()
    league.join_code = new_code
    league.updated_at = _now()
    db.add(
        AuditLog(
            actor_id=admin.id,
            actor_type=ActorType.admin,
            action=ActionType.league_join_code_rotated,
            target_table="leagues",
            target_id=league.id,
        )
    )
    await db.commit()
    return AdminRotateJoinCodeResponse(join_code=new_code)


@router.get("/players", response_model=list[AdminPlayerResponse])
async def list_all_players(
    admin: AdminPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
    include_deleted: bool = False,
) -> list[AdminPlayerResponse]:
    query = select(Profile)
    if not include_deleted:
        query = query.where(Profile.deleted_at.is_(None))
    query = query.order_by(Profile.created_at)
    result = await db.execute(query)
    players = result.scalars().all()
    return [
        AdminPlayerResponse(
            id=str(p.id),
            display_name=p.display_name,
            first_name=p.first_name,
            last_name=p.last_name,
            email=p.email,
            role=p.role.value,
            timezone=p.timezone,
            is_deleted=p.deleted_at is not None,
            created_at=p.created_at,
            failed_login_count=p.failed_login_count,
            locked_until=p.locked_until,
        )
        for p in players
    ]


@router.get("/invites", response_model=list[InviteResponse])
async def list_invites(
    admin: AdminPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[InviteResponse]:
    result = await db.execute(select(Invite).order_by(Invite.created_at.desc()))
    invites = result.scalars().all()
    return [_to_response(i) for i in invites]


@router.delete("/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite(
    invite_id: uuid.UUID,
    admin: AdminPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    result = await db.execute(select(Invite).where(Invite.id == invite_id))
    invite = result.scalar_one_or_none()
    if invite is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")

    invite.is_active = False
    await db.commit()
    log.info("invite revoked", invite_id=str(invite_id), admin_id=str(admin.id))


@router.post(
    "/players/{player_id}/reset-pin",
    response_model=ResetPinResponse,
    status_code=status.HTTP_200_OK,
)
async def reset_player_pin(
    player_id: uuid.UUID,
    admin: AdminPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ResetPinResponse:
    result = await db.execute(
        select(Profile).where(Profile.id == player_id, Profile.deleted_at.is_(None))
    )
    player = result.scalar_one_or_none()
    if player is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")

    temp_pin = f"{secrets.randbelow(1000000):06d}"
    player.pin_hash = hash_pin(temp_pin)
    await db.commit()

    log.info("pin reset by admin", player_id=str(player_id), admin_id=str(admin.id))
    return ResetPinResponse(temp_pin=temp_pin)


@router.post("/players/{player_id}/unlock", status_code=status.HTTP_204_NO_CONTENT)
async def unlock_player(
    player_id: uuid.UUID,
    admin: AdminPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    result = await db.execute(
        select(Profile).where(Profile.id == player_id, Profile.deleted_at.is_(None))
    )
    player = result.scalar_one_or_none()
    if player is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")

    player.failed_login_count = 0
    player.locked_until = None
    await db.commit()
    log.info("account unlocked by admin", player_id=str(player_id), admin_id=str(admin.id))


@router.post("/groups/{name}/override-standings", status_code=status.HTTP_204_NO_CONTENT)
async def override_standings(
    name: str,
    body: OverrideStandingsRequest,
    admin: AdminPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    result = await db.execute(select(Group).where(Group.name == name.upper()))
    group = result.scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    group.standings_override = body.positions
    await db.commit()
    log.info("standings override set", group=name.upper(), positions=body.positions)


# ---------------------------------------------------------------------------
# Tiebreak settlement (U38.4) — admin backstop for a genuine all-axis tie
# ---------------------------------------------------------------------------


async def _load_league_by_slug(db: AsyncSession, slug: str) -> League:
    league = (await db.execute(select(League).where(League.slug == slug))).scalar_one_or_none()
    if league is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="League not found")
    return league


async def _require_league_member(
    db: AsyncSession, league_id: uuid.UUID, player_id: uuid.UUID
) -> Profile:
    profile = (
        await db.execute(
            select(Profile)
            .join(
                LeagueMembership,
                (LeagueMembership.player_id == Profile.id)
                & (LeagueMembership.league_id == league_id)
                & (LeagueMembership.deleted_at.is_(None)),
            )
            .where(Profile.id == player_id, Profile.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Player is not an active member of this league",
        )
    return profile


@router.get(
    "/leagues/{slug}/tiebreak-overrides",
    response_model=list[TiebreakOverrideResponse],
)
async def list_tiebreak_overrides(
    slug: str,
    admin: AdminPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[TiebreakOverrideResponse]:
    """Current manual tiebreak orders for a league (normally empty)."""
    league = await _load_league_by_slug(db, slug)
    rows = (
        await db.execute(
            select(LeaderboardTiebreakOverride, Profile)
            .join(Profile, Profile.id == LeaderboardTiebreakOverride.player_id)
            .where(LeaderboardTiebreakOverride.league_id == league.id)
            .order_by(LeaderboardTiebreakOverride.manual_order.asc())
        )
    ).all()
    return [
        TiebreakOverrideResponse(
            league_slug=slug,
            player_id=str(ovr.player_id),
            player_name=profile.display_name,
            manual_order=ovr.manual_order,
            reason=ovr.reason,
        )
        for ovr, profile in rows
    ]


@router.put(
    "/leagues/{slug}/tiebreak/{player_id}",
    response_model=TiebreakOverrideResponse,
)
async def set_tiebreak_override(
    slug: str,
    player_id: uuid.UUID,
    body: TiebreakOverrideRequest,
    admin: AdminPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TiebreakOverrideResponse:
    """Settle a genuine all-axis tie by pinning a player's manual order.

    The merit cascade resolves every realistic tie; this is the no-arbitrary-
    rule backstop for the case where two players are level on *every* axis.
    Upserts the override, then recomputes snapshots so the new order flows to
    the table, history, and any rank-derived surface immediately.
    """
    league = await _load_league_by_slug(db, slug)
    profile = await _require_league_member(db, league.id, player_id)

    existing = (
        await db.execute(
            select(LeaderboardTiebreakOverride).where(
                LeaderboardTiebreakOverride.league_id == league.id,
                LeaderboardTiebreakOverride.player_id == player_id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(
            LeaderboardTiebreakOverride(
                league_id=league.id,
                player_id=player_id,
                manual_order=body.manual_order,
                reason=body.reason,
            )
        )
    else:
        existing.manual_order = body.manual_order
        existing.reason = body.reason

    db.add(
        AuditLog(
            actor_id=admin.id,
            actor_type=ActorType.admin,
            action_type=ActionType.tiebreaker_overridden,
            target_table="leaderboard_tiebreak_overrides",
            target_id=player_id,
            changes={
                "league": slug,
                "manual_order": body.manual_order,
                "reason": body.reason,
            },
        )
    )
    # Re-rank with the new override applied (writes fresh snapshots for everyone).
    await recompute_leaderboard_snapshot(db, triggered_by_match_id=None)
    await db.commit()
    log.info(
        "tiebreak override set",
        league=slug,
        player_id=str(player_id),
        manual_order=body.manual_order,
        admin_id=str(admin.id),
    )
    return TiebreakOverrideResponse(
        league_slug=slug,
        player_id=str(player_id),
        player_name=profile.display_name,
        manual_order=body.manual_order,
        reason=body.reason,
    )


@router.delete(
    "/leagues/{slug}/tiebreak/{player_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def clear_tiebreak_override(
    slug: str,
    player_id: uuid.UUID,
    admin: AdminPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Remove a manual tiebreak order, restoring the pure merit cascade."""
    league = await _load_league_by_slug(db, slug)
    existing = (
        await db.execute(
            select(LeaderboardTiebreakOverride).where(
                LeaderboardTiebreakOverride.league_id == league.id,
                LeaderboardTiebreakOverride.player_id == player_id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Override not found")
    await db.delete(existing)
    db.add(
        AuditLog(
            actor_id=admin.id,
            actor_type=ActorType.admin,
            action_type=ActionType.tiebreaker_overridden,
            target_table="leaderboard_tiebreak_overrides",
            target_id=player_id,
            changes={"league": slug, "cleared": True},
        )
    )
    await recompute_leaderboard_snapshot(db, triggered_by_match_id=None)
    await db.commit()
    log.info(
        "tiebreak override cleared",
        league=slug,
        player_id=str(player_id),
        admin_id=str(admin.id),
    )


@router.delete("/players/{player_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_player(
    player_id: uuid.UUID,
    admin: AdminPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    result = await db.execute(
        select(Profile).where(Profile.id == player_id, Profile.deleted_at.is_(None))
    )
    player = result.scalar_one_or_none()
    if player is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")

    player.deleted_at = _now()
    await db.commit()
    log.info("player soft-deleted", player_id=str(player_id), admin_id=str(admin.id))


async def _load_match(db: AsyncSession, match_id: uuid.UUID) -> Match:
    result = await db.execute(select(Match).where(Match.id == match_id, Match.deleted_at.is_(None)))
    match = result.scalar_one_or_none()
    if match is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Match not found")
    return match


def _strip_tz(dt: datetime) -> datetime:
    """Strip timezone from a datetime, normalising to UTC first if aware."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(UTC).replace(tzinfo=None)


def _match_admin_response(m: Match) -> MatchAdminResponse:
    return MatchAdminResponse(
        id=str(m.id),
        match_number=m.match_number,
        status=m.status.value,
        kickoff_utc=m.kickoff_utc,
        original_kickoff_utc=m.original_kickoff_utc,
        locked_at=m.locked_at,
        postponed_reason=m.postponed_reason,
    )


@router.post(
    "/matches/{match_id}/reschedule",
    response_model=MatchAdminResponse,
    status_code=status.HTTP_200_OK,
)
async def reschedule_match(
    match_id: uuid.UUID,
    body: RescheduleRequest,
    admin: AdminPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MatchAdminResponse:
    match = await _load_match(db, match_id)
    new_kickoff = _strip_tz(body.kickoff_utc)
    old_kickoff = match.kickoff_utc

    if match.original_kickoff_utc is None:
        match.original_kickoff_utc = old_kickoff

    match.kickoff_utc = new_kickoff

    # If the match was locked but is being rescheduled to a time later than
    # the lock instant, re-open it for predictions.
    if (
        match.status == MatchStatus.locked
        and match.locked_at is not None
        and match.locked_at < new_kickoff
    ):
        match.status = MatchStatus.scheduled
        match.locked_at = None

    db.add(
        AuditLog(
            actor_id=admin.id,
            actor_type=ActorType.admin,
            action_type=ActionType.kickoff_changed,
            target_table="matches",
            target_id=match.id,
            changes={
                "old_kickoff_utc": old_kickoff.isoformat(),
                "new_kickoff_utc": new_kickoff.isoformat(),
            },
        )
    )
    upd = MatchUpdate(
        event_type="kickoff_changed",
        match_id=match.id,
        stage=match.stage.value,
        home_team_id=match.home_team_id,
        away_team_id=match.away_team_id,
        home_placeholder=match.home_team_placeholder,
        away_placeholder=match.away_team_placeholder,
        old_kickoff=old_kickoff,
        new_kickoff=new_kickoff,
    )
    await db.commit()
    await notify_kickoff_changed(db, upd)
    await db.commit()
    await db.refresh(match)
    log.info(
        "match rescheduled",
        match_id=str(match.id),
        admin_id=str(admin.id),
        new_kickoff=new_kickoff.isoformat(),
    )
    return _match_admin_response(match)


@router.post(
    "/matches/{match_id}/postpone",
    response_model=MatchAdminResponse,
    status_code=status.HTTP_200_OK,
)
async def postpone_match(
    match_id: uuid.UUID,
    body: PostponeRequest,
    admin: AdminPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MatchAdminResponse:
    match = await _load_match(db, match_id)
    match.status = MatchStatus.postponed
    match.postponed_reason = body.reason

    db.add(
        AuditLog(
            actor_id=admin.id,
            actor_type=ActorType.admin,
            action_type=ActionType.match_postponed,
            target_table="matches",
            target_id=match.id,
            changes={"reason": body.reason},
        )
    )
    upd = MatchUpdate(
        event_type="postponed",
        match_id=match.id,
        stage=match.stage.value,
        home_team_id=match.home_team_id,
        away_team_id=match.away_team_id,
        home_placeholder=match.home_team_placeholder,
        away_placeholder=match.away_team_placeholder,
    )
    await db.commit()
    await notify_match_postponed(db, upd)
    await db.commit()
    await db.refresh(match)
    log.info("match postponed", match_id=str(match.id), admin_id=str(admin.id))
    return _match_admin_response(match)


@router.post(
    "/matches/{match_id}/cancel",
    response_model=MatchAdminResponse,
    status_code=status.HTTP_200_OK,
)
async def cancel_match(
    match_id: uuid.UUID,
    admin: AdminPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MatchAdminResponse:
    match = await _load_match(db, match_id)
    match.status = MatchStatus.cancelled

    # Zero any points already awarded for this match (spec §6.13). The
    # match-result trigger doesn't fire here (we're not touching
    # actual_*_score), so we recompute the leaderboard snapshot ourselves.
    await db.execute(
        update(Prediction).where(Prediction.match_id == match.id).values(points_awarded=0)
    )
    await db.execute(
        update(KnockoutPrediction)
        .where(KnockoutPrediction.match_id == match.id)
        .values(points_awarded=0)
    )
    await recompute_leaderboard_snapshot(db, triggered_by_match_id=match.id)

    db.add(
        AuditLog(
            actor_id=admin.id,
            actor_type=ActorType.admin,
            action_type=ActionType.match_cancelled,
            target_table="matches",
            target_id=match.id,
            changes=None,
        )
    )
    await db.commit()
    await db.refresh(match)
    log.info("match cancelled", match_id=str(match.id), admin_id=str(admin.id))
    return _match_admin_response(match)


@router.post(
    "/matches/{match_id}/lock",
    response_model=MatchAdminResponse,
    status_code=status.HTTP_200_OK,
)
async def lock_match(
    match_id: uuid.UUID,
    admin: AdminPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MatchAdminResponse:
    """Manually lock a scheduled match before its kickoff (GAP-07).

    Useful when the actual kickoff moves earlier than the stored kickoff_utc
    and the periodic lock job hasn't yet caught up.  Idempotent — locking an
    already-locked match is a no-op (returns the unchanged record).
    """
    match = await _load_match(db, match_id)
    if match.status == MatchStatus.locked:
        return _match_admin_response(match)

    if match.status not in {MatchStatus.scheduled}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot lock a match with status '{match.status.value}'",
        )

    match.status = MatchStatus.locked
    match.locked_at = _now()

    db.add(
        AuditLog(
            actor_id=admin.id,
            actor_type=ActorType.admin,
            action_type=ActionType.match_locked,
            target_table="matches",
            target_id=match.id,
            changes={"manual": True},
        )
    )
    await db.commit()
    await db.refresh(match)
    log.info("match manually locked", match_id=str(match.id), admin_id=str(admin.id))
    return _match_admin_response(match)


# ---------------------------------------------------------------------------
# Results endpoints (5.1)
# ---------------------------------------------------------------------------


async def _maybe_resync_knockout(db: AsyncSession, match: Match) -> None:
    """Best-effort: propagate a settled result into the seeded knockout bracket.

    Filling placeholder slots with real teams must never block result entry, so
    any failure is logged and swallowed. Guarded on a real ``TournamentStage``
    so HTTP unit tests whose mocked ``Match.stage`` is a ``MagicMock`` skip the
    call (and never touch the mocked session's fixed execute queue).
    """
    if not isinstance(match.stage, TournamentStage):
        return
    try:
        await sync_knockout_bracket(db)
    except Exception:  # noqa: BLE001 — knockout resolution is advisory, never fatal
        log.warning("knockout resync failed", match_id=str(match.id), exc_info=True)


@router.post(
    "/results/{match_id}",
    response_model=ResultResponse,
    status_code=status.HTTP_200_OK,
)
async def enter_result(
    match_id: uuid.UUID,
    body: ResultRequest,
    admin: AdminPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ResultResponse:
    """Manual result entry — used when auto-fetch has not populated the result."""
    result = await db.execute(select(Match).where(Match.id == match_id, Match.deleted_at.is_(None)))
    match = result.scalar_one_or_none()
    if match is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Match not found")

    if match.status not in _VALID_RESULT_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Cannot enter result for a match with status '{match.status}'",
        )

    if match.result_source is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Match already has a result. Use PUT /admin/results/{match_id} to override.",
        )

    penalty_winner_id = uuid.UUID(body.penalty_winner_id) if body.penalty_winner_id else None

    before: dict[str, object] = {
        "actual_home_score": match.actual_home_score,
        "actual_away_score": match.actual_away_score,
        "result_source": None,
    }

    match.actual_home_score = body.actual_home_score
    match.actual_away_score = body.actual_away_score
    match.extra_time = body.extra_time
    match.penalties = body.penalties
    match.penalty_winner_id = penalty_winner_id
    match.result_source = ResultSource.manual
    match.result_entered_by = admin.id
    match.status = MatchStatus.completed
    # result_entered_at is stamped atomically by the BEFORE trigger

    db.add(
        AuditLog(
            actor_id=admin.id,
            actor_type=ActorType.admin,
            action_type=ActionType.result_manual_entered,
            target_table="matches",
            target_id=match_id,
            changes={
                "before": before,
                "after": {
                    "actual_home_score": body.actual_home_score,
                    "actual_away_score": body.actual_away_score,
                    "result_source": ResultSource.manual.value,
                },
            },
        )
    )

    await db.commit()
    await db.refresh(match)
    response = _to_result_response(match)

    await _maybe_resync_knockout(db, match)

    log.info("result entered manually", match_id=str(match_id), admin_id=str(admin.id))
    return response


@router.put(
    "/results/{match_id}",
    response_model=ResultResponse,
    status_code=status.HTTP_200_OK,
)
async def override_result(
    match_id: uuid.UUID,
    body: ResultRequest,
    admin: AdminPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ResultResponse:
    """Override an existing result and trigger a full points recalculation."""
    result = await db.execute(select(Match).where(Match.id == match_id, Match.deleted_at.is_(None)))
    match = result.scalar_one_or_none()
    if match is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Match not found")

    if match.status not in _VALID_RESULT_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Cannot override result for a match with status '{match.status}'",
        )

    if match.result_source is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Match has no prior result. Use POST /admin/results/{match_id} to enter one.",
        )

    before: dict[str, object] = {
        "actual_home_score": match.actual_home_score,
        "actual_away_score": match.actual_away_score,
        "result_source": match.result_source.value,
    }

    penalty_winner_id = uuid.UUID(body.penalty_winner_id) if body.penalty_winner_id else None

    match.actual_home_score = body.actual_home_score
    match.actual_away_score = body.actual_away_score
    match.extra_time = body.extra_time
    match.penalties = body.penalties
    match.penalty_winner_id = penalty_winner_id
    match.result_source = ResultSource.override
    match.result_entered_by = admin.id
    match.status = MatchStatus.completed

    db.add(
        AuditLog(
            actor_id=admin.id,
            actor_type=ActorType.admin,
            action_type=ActionType.result_overridden,
            target_table="matches",
            target_id=match_id,
            changes={
                "before": before,
                "after": {
                    "actual_home_score": body.actual_home_score,
                    "actual_away_score": body.actual_away_score,
                    "result_source": ResultSource.override.value,
                },
            },
        )
    )

    await db.commit()
    await db.refresh(match)
    response = _to_result_response(match)

    await _maybe_resync_knockout(db, match)

    log.info("result overridden", match_id=str(match_id), admin_id=str(admin.id))
    return response


# ---------------------------------------------------------------------------
# Admin dashboard
# ---------------------------------------------------------------------------


@router.get("/dashboard", response_model=AdminDashboardResponse)
async def get_dashboard(
    admin: AdminPlayer,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AdminDashboardResponse:
    """Return all widgets for the admin dashboard in a single request."""
    from src.models.team import Team

    now = _now()
    window_end = now + timedelta(hours=24)

    # Active players (non-deleted, non-admin for the count)
    active_result = await db.execute(select(Profile).where(Profile.deleted_at.is_(None)))
    players = list(active_result.scalars().all())
    active_players = len(players)

    # Upcoming locks: scheduled matches kicking off in next 24 h
    locks_result = await db.execute(
        select(Match)
        .where(
            Match.status == MatchStatus.scheduled,
            Match.kickoff_utc >= now,
            Match.kickoff_utc <= window_end,
            Match.deleted_at.is_(None),
        )
        .order_by(Match.kickoff_utc)
        .limit(20)
    )
    lock_matches = list(locks_result.scalars().all())

    # Pending result: locked/live matches that have no result yet
    pending_result = await db.execute(
        select(Match)
        .where(
            Match.status.in_([MatchStatus.locked, MatchStatus.live]),
            Match.result_source.is_(None),
            Match.deleted_at.is_(None),
        )
        .order_by(Match.kickoff_utc)
        .limit(20)
    )
    pending_matches = list(pending_result.scalars().all())

    # Build team name map for both sets
    all_team_ids = (
        {m.home_team_id for m in lock_matches}
        | {m.away_team_id for m in lock_matches}
        | {m.home_team_id for m in pending_matches}
        | {m.away_team_id for m in pending_matches}
    )
    all_team_ids.discard(None)
    team_map: dict[uuid.UUID, str] = {}
    if all_team_ids:
        teams_result = await db.execute(select(Team).where(Team.id.in_(list(all_team_ids))))
        for t in teams_result.scalars().all():
            team_map[t.id] = t.name

    # Recent audit entries (last 10)
    audit_result = await db.execute(select(AuditLog).order_by(desc(AuditLog.timestamp)).limit(10))
    audit_rows = list(audit_result.scalars().all())

    # Sync status (reuse existing helper)
    sync = await get_sync_status(admin, request, db)

    def _team_name(tid: uuid.UUID | None, placeholder: str | None) -> str | None:
        if tid and tid in team_map:
            return team_map[tid]
        return placeholder

    return AdminDashboardResponse(
        active_players=active_players,
        upcoming_locks=[
            UpcomingLockResponse(
                match_id=str(m.id),
                match_number=m.match_number,
                kickoff_utc=m.kickoff_utc,
                home_team=_team_name(m.home_team_id, m.home_team_placeholder),
                away_team=_team_name(m.away_team_id, m.away_team_placeholder),
                minutes_until_lock=max(0, int((m.kickoff_utc - now).total_seconds() // 60)),
            )
            for m in lock_matches
        ],
        pending_result_matches=[
            AdminMatchResultResponse(
                match_id=str(m.id),
                match_number=m.match_number,
                status=m.status.value,
                kickoff_utc=m.kickoff_utc,
                home_team=_team_name(m.home_team_id, m.home_team_placeholder),
                away_team=_team_name(m.away_team_id, m.away_team_placeholder),
                actual_home_score=m.actual_home_score,
                actual_away_score=m.actual_away_score,
                extra_time=m.extra_time,
                penalties=m.penalties,
                result_source=m.result_source.value if m.result_source else None,
                result_entered_at=m.result_entered_at,
            )
            for m in pending_matches
        ],
        recent_audit=[
            DashboardAuditEntry(
                id=str(a.id),
                action_type=a.action_type.value,
                actor_type=a.actor_type.value,
                timestamp=a.timestamp,
                target_table=a.target_table,
            )
            for a in audit_rows
        ],
        sync_status=sync,
    )


# ---------------------------------------------------------------------------
# Sync status / trigger
# ---------------------------------------------------------------------------


@router.get("/sync/status", response_model=SyncStatusResponse)
async def get_sync_status(
    _admin: AdminPlayer,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SyncStatusResponse:
    """Return the last sync timestamp, next scheduled run, and recent errors."""
    # Latest system audit row that relates to a sync activity
    last_row_result = await db.execute(
        select(AuditLog)
        .where(
            AuditLog.actor_type == ActorType.system,
            AuditLog.action_type.in_(list(_SYNC_ACTION_TYPES)),
        )
        .order_by(desc(AuditLog.timestamp))
        .limit(1)
    )
    last_row = last_row_result.scalar_one_or_none()

    # Recent failures
    errors_result = await db.execute(
        select(AuditLog)
        .where(
            AuditLog.actor_type == ActorType.system,
            AuditLog.action_type == ActionType.sync_failed,
        )
        .order_by(desc(AuditLog.timestamp))
        .limit(5)
    )
    errors = list(errors_result.scalars().all())

    # Next scheduled run from APScheduler
    next_run_at: datetime | None = None
    try:
        job = request.app.state.scheduler.get_job("sync_results")
        if job and job.next_run_time:
            next_run_at = job.next_run_time.replace(tzinfo=None)
    except Exception:
        pass

    return SyncStatusResponse(
        last_sync_at=last_row.timestamp if last_row else None,
        last_sync_action=last_row.action_type.value if last_row else None,
        next_run_at=next_run_at,
        recent_errors=[
            AuditEntryResponse(
                id=str(e.id),
                action_type=e.action_type.value,
                timestamp=e.timestamp,
                changes=e.changes,
            )
            for e in errors
        ],
    )


@router.post("/sync/trigger", response_model=SyncStatusResponse, status_code=status.HTTP_200_OK)
@limiter.limit("10/hour", key_func=per_player_key)
async def trigger_sync(
    admin: AdminPlayer,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SyncStatusResponse:
    """Manually kick off an immediate sync and return the updated sync status."""
    log.info("manual sync triggered", admin_id=str(admin.id))
    await sync_results()
    return await get_sync_status(admin, request, db)


# ---------------------------------------------------------------------------
# Admin results list
# ---------------------------------------------------------------------------


async def _build_match_result_responses(
    db: AsyncSession, matches: list[Match]
) -> list[AdminMatchResultResponse]:
    """Resolve team names for ``matches`` and build the admin result rows.

    Shared by the completed-results list and the pending-results list so both
    expose the same shape (including team ids + stage, which the admin entry
    form needs to offer a penalty-winner choice on knockout draws).
    """
    from src.models.team import Team

    all_team_ids = {m.home_team_id for m in matches} | {m.away_team_id for m in matches}
    all_team_ids.discard(None)
    team_map: dict[uuid.UUID, str] = {}
    if all_team_ids:
        teams_result = await db.execute(select(Team).where(Team.id.in_(list(all_team_ids))))
        for t in teams_result.scalars().all():
            team_map[t.id] = t.name

    return [
        AdminMatchResultResponse(
            match_id=str(m.id),
            match_number=m.match_number,
            status=m.status.value,
            stage=m.stage.value,
            kickoff_utc=m.kickoff_utc,
            home_team=team_map.get(m.home_team_id) if m.home_team_id else m.home_team_placeholder,
            away_team=team_map.get(m.away_team_id) if m.away_team_id else m.away_team_placeholder,
            home_team_id=str(m.home_team_id) if m.home_team_id else None,
            away_team_id=str(m.away_team_id) if m.away_team_id else None,
            actual_home_score=m.actual_home_score,
            actual_away_score=m.actual_away_score,
            extra_time=m.extra_time,
            penalties=m.penalties,
            result_source=m.result_source.value if m.result_source else None,
            result_entered_at=m.result_entered_at,
        )
        for m in matches
    ]


@router.get("/results", response_model=list[AdminMatchResultResponse])
async def list_results(
    _admin: AdminPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[AdminMatchResultResponse]:
    """List all completed matches with their result sources."""
    result = await db.execute(
        select(Match)
        .where(
            Match.status == MatchStatus.completed,
            Match.deleted_at.is_(None),
        )
        .order_by(desc(Match.result_entered_at))
        .limit(100)
    )
    return await _build_match_result_responses(db, list(result.scalars().all()))


@router.get("/results/pending", response_model=list[AdminMatchResultResponse])
async def list_pending_results(
    _admin: AdminPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[AdminMatchResultResponse]:
    """List matches awaiting a result — locked or live with no result yet.

    This is the manual-entry fallback surface for when auto-fetch has not
    populated a result (the C-P0 auto-fetch path can stall on upstream
    outages). The admin enters a result here via ``POST /admin/results/{id}``.
    """
    result = await db.execute(
        select(Match)
        .where(
            Match.status.in_([MatchStatus.locked, MatchStatus.live]),
            Match.result_source.is_(None),
            Match.deleted_at.is_(None),
        )
        .order_by(Match.kickoff_utc)
        .limit(100)
    )
    return await _build_match_result_responses(db, list(result.scalars().all()))


# ---------------------------------------------------------------------------
# Knockout advancement (Phase 7.1)
# ---------------------------------------------------------------------------


async def _default_fd_fetcher() -> list[FDMatch]:
    """Live football-data.org fetcher used in production.

    A dependency so tests can override it via ``app.dependency_overrides``
    without monkey-patching the client.
    """
    client = FootballDataClient(api_key=settings.football_data_api_key)
    try:
        response = await client.get_competition_matches()
        return response.matches
    finally:
        await client.close()


def get_fd_fetcher() -> FdFetcher:
    return _default_fd_fetcher


@router.post(
    "/knockout/advance",
    response_model=KnockoutAdvanceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def advance_knockout(
    body: KnockoutAdvanceRequest,
    admin: AdminPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
    fd_fetcher: Annotated[FdFetcher, Depends(get_fd_fetcher)],
) -> KnockoutAdvanceResponse:
    """Create the next round's matches from completed prior-round results.

    Phase 7.1 implements the ``group → r32`` advancement only. Subsequent
    rounds will be handled in later phases of the architecture plan.
    """
    if body.from_stage != "group":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Advancement from stage '{body.from_stage}' is not yet supported",
        )

    try:
        matches = await advance_to_r32(db, admin.id, fd_fetcher)
    except AlreadyAdvancedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except GroupStageIncompleteError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except MissingKickoffsError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except FootballDataError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"football-data.org request failed: {exc}",
        ) from exc

    return KnockoutAdvanceResponse(
        to_stage="r32",
        matches=[
            KnockoutMatchResponse(
                id=str(m.id),
                match_number=m.match_number,
                stage=m.stage.value,
                kickoff_utc=m.kickoff_utc,
                home_team_id=str(m.home_team_id),
                away_team_id=str(m.away_team_id),
                home_team_placeholder=m.home_team_placeholder or "",
                away_team_placeholder=m.away_team_placeholder or "",
                football_data_match_id=m.football_data_match_id,
            )
            for m in matches
        ],
    )


# ---------------------------------------------------------------------------
# Backup endpoints (Phase 11.4)
# ---------------------------------------------------------------------------


class BackupResponse(BaseModel):
    filename: str
    size_bytes: int
    created_at: datetime


def _to_backup_response(info: BackupInfo) -> BackupResponse:
    return BackupResponse(
        filename=info.filename,
        size_bytes=info.size_bytes,
        created_at=info.created_at,
    )


@router.post(
    "/backup",
    response_model=BackupResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("5/day", key_func=per_player_key)
async def trigger_backup(request: Request, admin: AdminPlayer) -> BackupResponse:
    """Create a new pg_dump backup of the database."""
    log.info("manual backup triggered", admin_id=str(admin.id))
    try:
        info = await create_backup(settings.backup_dir, settings.database_url)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Backup failed: {exc}",
        ) from exc
    return _to_backup_response(info)


@router.get("/backups", response_model=list[BackupResponse])
async def get_backups(_admin: AdminPlayer) -> list[BackupResponse]:
    """List all available backups, newest first."""
    return [_to_backup_response(i) for i in list_backups(settings.backup_dir)]


@router.get("/backups/{filename}")
async def download_backup(
    admin: AdminPlayer,
    filename: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FileResponse:
    """Download a backup file."""
    try:
        path = resolve_backup_path(settings.backup_dir, filename)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backup not found")
    db.add(
        AuditLog(
            actor_id=admin.id,
            actor_type=ActorType.player,
            action_type=ActionType.backup_downloaded,
            target_table=None,
            target_id=None,
            changes={"filename": filename},
        )
    )
    await db.commit()
    return FileResponse(
        path=str(path),
        media_type="application/octet-stream",
        filename=filename,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_response(invite: Invite) -> InviteResponse:
    return InviteResponse(
        id=str(invite.id),
        token=invite.token,
        display_name_hint=invite.display_name_hint,
        created_by=str(invite.created_by),
        claimed_by=str(invite.claimed_by) if invite.claimed_by else None,
        claimed_at=invite.claimed_at,
        expires_at=invite.expires_at,
        is_active=invite.is_active,
        created_at=invite.created_at,
    )


def _to_result_response(match: Match) -> ResultResponse:
    return ResultResponse(
        match_id=str(match.id),
        actual_home_score=match.actual_home_score if match.actual_home_score is not None else 0,
        actual_away_score=match.actual_away_score if match.actual_away_score is not None else 0,
        extra_time=match.extra_time,
        penalties=match.penalties,
        penalty_winner_id=str(match.penalty_winner_id) if match.penalty_winner_id else None,
        result_source=match.result_source.value if match.result_source else "manual",
        result_entered_at=match.result_entered_at,
        result_entered_by=str(match.result_entered_by) if match.result_entered_by else None,
        status=match.status.value,
    )
