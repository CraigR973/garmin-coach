"""Dev/test-only fixture endpoints — never registered in production.

Registered by main.py only when settings.environment != "production".
Provides idempotent seed/cleanup and a scheduler bypass for the Playwright
smoke test: join → predict → lock → result → leaderboard.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import hash_pin
from src.database import get_db
from src.models.group import Group
from src.models.invite import Invite
from src.models.league import League
from src.models.league_membership import LeagueMemberRole, LeagueMembership
from src.models.match import Match, MatchStatus
from src.models.prediction import NotificationPreferences
from src.models.profile import PlayerRole, Profile, SiteRole
from src.models.refresh_token import RefreshToken
from src.models.team import Team, TournamentStage

log = structlog.get_logger()

router = APIRouter(prefix="/api/v1/test", tags=["test-helpers"])

# Fixed identifiers — chosen to avoid collisions with any real tournament data.
_ADMIN_NAME = "__smoke_admin__"
_ADMIN_EMAIL = "smoke-admin@test.invalid"
_ADMIN_PIN = "1111"
_PLAYER_NAME = "SmokePlayer"
_MATCH_NUMBER = 9901
_HOME_CODE = "SMK"
_AWAY_CODE = "TST"
_GROUP_NAME = "Z"
# M2 — the global API surface still routes through the Steele league. The
# smoke seed materialises it (idempotent) so create_invite + the leaderboard
# query both succeed in a fresh CI database where no backfill has run.
_DEFAULT_LEAGUE_SLUG = "steele-spreadsheet"
_DEFAULT_LEAGUE_NAME = "The Steele Spreadsheet"


class SeedResponse(BaseModel):
    admin_display_name: str
    admin_email: str
    admin_pin: str
    match_id: str


@router.post("/seed", response_model=SeedResponse)
async def seed(db: Annotated[AsyncSession, Depends(get_db)]) -> SeedResponse:
    """Create smoke-test fixtures (idempotent — safe to call multiple times)."""
    # Admin profile
    admin_q = await db.execute(
        select(Profile).where(
            Profile.display_name == _ADMIN_NAME,
            Profile.deleted_at.is_(None),
        )
    )
    admin = admin_q.scalar_one_or_none()
    if admin is None:
        admin = Profile(
            id=uuid.uuid4(),
            display_name=_ADMIN_NAME,
            pin_hash=hash_pin(_ADMIN_PIN),
            role=PlayerRole.admin,
            timezone="UTC",
            failed_login_count=0,
            email=_ADMIN_EMAIL,
            first_name="Smoke",
            last_name="Admin",
            site_role=SiteRole.superadmin,
        )
        db.add(admin)
        await db.flush()
        db.add(NotificationPreferences(player_id=admin.id))
        await db.flush()

    # Default league (steele-spreadsheet) — M2 invites/leaderboard depend on it.
    league_q = await db.execute(select(League).where(League.slug == _DEFAULT_LEAGUE_SLUG))
    league = league_q.scalar_one_or_none()
    if league is None:
        league = League(
            id=uuid.uuid4(),
            slug=_DEFAULT_LEAGUE_SLUG,
            name=_DEFAULT_LEAGUE_NAME,
            created_by=admin.id,
        )
        db.add(league)
        await db.flush()

    # Admin's league membership (idempotent — the (league_id, player_id) UNIQUE
    # prevents duplicates and we explicitly look it up first).
    membership_q = await db.execute(
        select(LeagueMembership).where(
            LeagueMembership.league_id == league.id,
            LeagueMembership.player_id == admin.id,
        )
    )
    if membership_q.scalar_one_or_none() is None:
        db.add(
            LeagueMembership(
                league_id=league.id,
                player_id=admin.id,
                role=LeagueMemberRole.admin,
            )
        )
        await db.flush()

    # Group (name must be ≤ 1 char per the schema)
    group_q = await db.execute(select(Group).where(Group.name == _GROUP_NAME))
    group = group_q.scalar_one_or_none()
    if group is None:
        group = Group(id=uuid.uuid4(), name=_GROUP_NAME)
        db.add(group)
        await db.flush()

    # Home team
    home_q = await db.execute(select(Team).where(Team.code == _HOME_CODE))
    home = home_q.scalar_one_or_none()
    if home is None:
        home = Team(
            id=uuid.uuid4(),
            name="Smoke Home",
            code=_HOME_CODE,
            flag_emoji="🧪",
            group_id=group.id,
        )
        db.add(home)
        await db.flush()

    # Away team
    away_q = await db.execute(select(Team).where(Team.code == _AWAY_CODE))
    away = away_q.scalar_one_or_none()
    if away is None:
        away = Team(
            id=uuid.uuid4(),
            name="Test Away",
            code=_AWAY_CODE,
            flag_emoji="🔬",
            group_id=group.id,
        )
        db.add(away)
        await db.flush()

    # Match (kickoff 2 h from now so predictions are open)
    match_q = await db.execute(select(Match).where(Match.match_number == _MATCH_NUMBER))
    match = match_q.scalar_one_or_none()
    if match is None:
        match = Match(
            id=uuid.uuid4(),
            stage=TournamentStage.group,
            group_id=group.id,
            match_number=_MATCH_NUMBER,
            home_team_id=home.id,
            away_team_id=away.id,
            kickoff_utc=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=2),
            venue="Smoke Stadium",
            status=MatchStatus.scheduled,
        )
        db.add(match)
        await db.flush()

    await db.commit()
    log.info("smoke seed ready", match_id=str(match.id))
    return SeedResponse(
        admin_display_name=_ADMIN_NAME,
        admin_email=_ADMIN_EMAIL,
        admin_pin=_ADMIN_PIN,
        match_id=str(match.id),
    )


@router.post("/lock-now/{match_id}", status_code=status.HTTP_204_NO_CONTENT)
async def lock_now(
    match_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Set a match's kickoff to 1 min ago and status=locked, bypassing the scheduler."""
    q = await db.execute(select(Match).where(Match.id == match_id))
    match = q.scalar_one_or_none()
    if match is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Match not found")
    match.kickoff_utc = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1)
    match.status = MatchStatus.locked
    await db.commit()
    log.info("smoke: match locked", match_id=str(match_id))


@router.delete("/cleanup", status_code=status.HTTP_204_NO_CONTENT)
async def cleanup(db: Annotated[AsyncSession, Depends(get_db)]) -> None:
    """Delete all rows created by seed() — idempotent, safe to call before/after each run.

    The default league row itself survives across runs (it is a fixture, not
    test scratch). Smoke memberships are deleted explicitly because the
    league_memberships → profiles FK has no ondelete cascade.
    """
    smoke_profile_q = select(Profile.id).where(
        Profile.display_name.in_([_ADMIN_NAME, _PLAYER_NAME])
    )
    # Explicit FK-ordered deletions for tables without ondelete=CASCADE on profiles.
    await db.execute(delete(Invite).where(Invite.created_by.in_(smoke_profile_q)))
    await db.execute(
        delete(LeagueMembership).where(LeagueMembership.player_id.in_(smoke_profile_q))
    )
    await db.execute(delete(RefreshToken).where(RefreshToken.player_id.in_(smoke_profile_q)))
    # Predictions cascade from Match via ondelete=CASCADE.
    await db.execute(delete(Match).where(Match.match_number == _MATCH_NUMBER))
    await db.execute(delete(Team).where(Team.code.in_([_HOME_CODE, _AWAY_CODE])))
    await db.execute(delete(Group).where(Group.name == _GROUP_NAME))
    # Profiles last — cascades notification_preferences, leaderboard_snapshots, notification_log.
    await db.execute(delete(Profile).where(Profile.display_name.in_([_ADMIN_NAME, _PLAYER_NAME])))
    await db.commit()
    log.info("smoke cleanup done")
