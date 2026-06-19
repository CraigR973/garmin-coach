"""Player profile endpoints."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import asc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import CurrentPlayer
from src.database import get_db
from src.deps import shared_league_player_ids
from src.models.league_membership import LeagueMembership
from src.models.match import Match
from src.models.prediction import KnockoutPrediction, Prediction, SpecialPrediction
from src.models.profile import Profile
from src.models.team import Team, TournamentStage
from src.reveal_gate import match_prediction_revealed, now_utc, specials_revealed
from src.routers.leagues import LeagueMemberDep

router = APIRouter(prefix="/api/v1/players", tags=["players"])
league_router = APIRouter(prefix="/api/v1/leagues", tags=["players"])


class PlayerProfileResponse(BaseModel):
    id: str
    display_name: str
    role: str
    timezone: str
    is_deleted: bool
    created_at: datetime


@league_router.get("/{slug}/players", response_model=list[PlayerProfileResponse])
async def list_league_players(
    ctx: LeagueMemberDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[PlayerProfileResponse]:
    """Active members of one league, in join order.

    Replaces the v1 global player list. ``role`` is the per-league membership
    role and ``display_name`` honours any per-league override (MD-11).
    """
    _player, league = ctx
    rows = (
        await db.execute(
            select(Profile, LeagueMembership)
            .join(LeagueMembership, LeagueMembership.player_id == Profile.id)
            .where(
                LeagueMembership.league_id == league.id,
                LeagueMembership.deleted_at.is_(None),
                Profile.deleted_at.is_(None),
            )
            .order_by(LeagueMembership.joined_at)
        )
    ).all()
    return [
        PlayerProfileResponse(
            id=str(profile.id),
            display_name=membership.display_name_override or profile.display_name,
            role=membership.role.value,
            timezone=profile.timezone,
            is_deleted=profile.deleted_at is not None,
            created_at=profile.created_at,
        )
        for profile, membership in rows
    ]


@router.get("/{player_id}", response_model=PlayerProfileResponse)
async def get_player(
    player_id: uuid.UUID,
    requester: CurrentPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PlayerProfileResponse:
    result = await db.execute(select(Profile).where(Profile.id == player_id))
    player = result.scalar_one_or_none()
    if player is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")
    shared = await shared_league_player_ids(requester.id, db)
    if player_id not in shared:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not share a league with this player",
        )
    return _to_response(player)


def _to_response(p: Profile) -> PlayerProfileResponse:
    return PlayerProfileResponse(
        id=str(p.id),
        display_name=p.display_name,
        role=p.role.value,
        timezone=p.timezone,
        is_deleted=p.deleted_at is not None,
        created_at=p.created_at,
    )


class RecentPredictionItem(BaseModel):
    match_id: str
    stage: str
    kickoff_utc: str
    home_team_name: str | None
    away_team_name: str | None
    home_team_flag: str | None
    away_team_flag: str | None
    actual_home: int | None
    actual_away: int | None
    predicted_home: int | None
    predicted_away: int | None
    points_awarded: int | None
    points_breakdown: dict[str, Any] | None = None


@router.get("/{player_id}/predictions/recent", response_model=list[RecentPredictionItem])
async def get_recent_predictions(
    player_id: uuid.UUID,
    requester: CurrentPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=5, ge=1, le=20),
) -> list[RecentPredictionItem]:
    """Recent settled group predictions for a player, newest first."""
    result = await db.execute(
        select(Profile).where(Profile.id == player_id, Profile.deleted_at.is_(None))
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")
    shared = await shared_league_player_ids(requester.id, db)
    if player_id not in shared:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not share a league with this player",
        )

    pred_stmt = (
        select(Prediction, Match)
        .join(Match, Match.id == Prediction.match_id)
        .where(
            Prediction.player_id == player_id,
            Prediction.deleted_at.is_(None),
            Prediction.points_awarded.is_not(None),
            Match.deleted_at.is_(None),
        )
        .order_by(Match.kickoff_utc.desc())
        .limit(limit)
    )
    pred_rows = (await db.execute(pred_stmt)).all()

    # Collect team IDs for a single batch fetch
    team_ids: set[uuid.UUID] = set()
    for _, match in pred_rows:
        if match.home_team_id is not None:
            team_ids.add(match.home_team_id)
        if match.away_team_id is not None:
            team_ids.add(match.away_team_id)

    teams: dict[str, Team] = {}
    if team_ids:
        team_result = await db.execute(select(Team).where(Team.id.in_(team_ids)))
        teams = {str(t.id): t for t in team_result.scalars().all()}

    return [
        RecentPredictionItem(
            match_id=str(match.id),
            stage=match.stage.value,
            kickoff_utc=match.kickoff_utc.isoformat() + "Z",
            home_team_name=teams[str(match.home_team_id)].name
            if match.home_team_id and str(match.home_team_id) in teams
            else match.home_team_placeholder,
            away_team_name=teams[str(match.away_team_id)].name
            if match.away_team_id and str(match.away_team_id) in teams
            else match.away_team_placeholder,
            home_team_flag=teams[str(match.home_team_id)].flag_emoji
            if match.home_team_id and str(match.home_team_id) in teams
            else None,
            away_team_flag=teams[str(match.away_team_id)].flag_emoji
            if match.away_team_id and str(match.away_team_id) in teams
            else None,
            actual_home=match.actual_home_score,
            actual_away=match.actual_away_score,
            predicted_home=pred.predicted_home,
            predicted_away=pred.predicted_away,
            points_awarded=pred.points_awarded,
            points_breakdown=pred.points_breakdown,
        )
        for pred, match in pred_rows
    ]


# ---------------------------------------------------------------------------
# GET /api/v1/players/{player_id}/profile-predictions  (U24)
#
# The full reveal-gated prediction board for a player's profile: group,
# knockout, and special predictions, each filtered through the SINGLE shared
# reveal gate (src.reveal_gate) so the privacy invariant is enforced in one
# place. A prediction is included only once it has locked:
#   * group / knockout → its own match has kicked off (or been voided)
#   * specials          → the tournament has started (opening kickoff passed)
# Pre-lock predictions are silently dropped — never returned, never an error
# row — so the endpoint can never leak an unlocked pick.
# ---------------------------------------------------------------------------


class GroupProfilePrediction(BaseModel):
    match_id: str
    stage: str
    kickoff_utc: str
    home_team_name: str | None
    away_team_name: str | None
    home_team_flag: str | None
    away_team_flag: str | None
    actual_home: int | None
    actual_away: int | None
    predicted_home: int | None
    predicted_away: int | None
    points_awarded: int | None
    points_breakdown: dict[str, Any] | None = None


class KnockoutProfilePrediction(BaseModel):
    match_id: str
    stage: str
    kickoff_utc: str
    home_team_name: str | None
    away_team_name: str | None
    home_team_flag: str | None
    away_team_flag: str | None
    predicted_winner_id: str | None
    predicted_winner_name: str | None
    points_awarded: int | None


class SpecialProfilePrediction(BaseModel):
    prediction_type: str
    predicted_team_id: str | None
    predicted_team_name: str | None
    predicted_player_name: str | None
    points_awarded: int | None


class ProfilePredictionsResponse(BaseModel):
    # ``specials_revealed`` lets the UI distinguish "no specials submitted" from
    # "specials hidden until the tournament starts" without leaking the picks.
    specials_revealed: bool
    group: list[GroupProfilePrediction]
    knockout: list[KnockoutProfilePrediction]
    specials: list[SpecialProfilePrediction]


def _team_name(team: Team | None, placeholder: str | None) -> str | None:
    return team.name if team is not None else placeholder


@router.get("/{player_id}/profile-predictions", response_model=ProfilePredictionsResponse)
async def get_profile_predictions(
    player_id: uuid.UUID,
    requester: CurrentPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProfilePredictionsResponse:
    """All of a player's locked predictions, grouped by kind, for their profile.

    Privacy invariant (U24): only predictions whose lock has passed are ever
    returned, and only to a league-mate. The same :mod:`src.reveal_gate`
    predicate guards every section.
    """
    result = await db.execute(
        select(Profile).where(Profile.id == player_id, Profile.deleted_at.is_(None))
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")
    shared = await shared_league_player_ids(requester.id, db)
    if player_id not in shared:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not share a league with this player",
        )

    now = now_utc()

    # --- Group predictions: join to match, keep only locked matches ---------
    group_raw = (
        await db.execute(
            select(Prediction, Match)
            .join(Match, Match.id == Prediction.match_id)
            .where(
                Prediction.player_id == player_id,
                Prediction.deleted_at.is_(None),
                Match.deleted_at.is_(None),
                Match.stage == TournamentStage.group,
            )
            .order_by(Match.kickoff_utc.desc())
        )
    ).all()
    group_rows = [(p, m) for (p, m) in group_raw if match_prediction_revealed(m, now)]

    # --- Knockout predictions: join to match, keep only locked matches ------
    ko_raw = (
        await db.execute(
            select(KnockoutPrediction, Match)
            .join(Match, Match.id == KnockoutPrediction.match_id)
            .where(
                KnockoutPrediction.player_id == player_id,
                Match.deleted_at.is_(None),
            )
            .order_by(Match.kickoff_utc.desc())
        )
    ).all()
    ko_rows = [(p, m) for (p, m) in ko_raw if match_prediction_revealed(m, now)]

    # --- Specials: revealed as a set once the tournament has started --------
    opening_match = (
        await db.execute(
            select(Match)
            .where(Match.stage == TournamentStage.group, Match.deleted_at.is_(None))
            .order_by(asc(Match.kickoff_utc))
            .limit(1)
        )
    ).scalar_one_or_none()
    specials_open = specials_revealed(opening_match, now)
    special_rows: list[SpecialPrediction] = []
    if specials_open:
        special_rows = list(
            (
                await db.execute(
                    select(SpecialPrediction).where(SpecialPrediction.player_id == player_id)
                )
            )
            .scalars()
            .all()
        )

    # --- Batch-fetch every team referenced across all three sections --------
    team_ids: set[uuid.UUID] = set()
    for _, match in group_rows:
        team_ids.update(t for t in (match.home_team_id, match.away_team_id) if t)
    for kpred, match in ko_rows:
        team_ids.update(t for t in (match.home_team_id, match.away_team_id) if t)
        if kpred.predicted_winner_id:
            team_ids.add(kpred.predicted_winner_id)
    for spred in special_rows:
        if spred.predicted_team_id:
            team_ids.add(spred.predicted_team_id)

    teams: dict[uuid.UUID, Team] = {}
    if team_ids:
        teams = {
            t.id: t
            for t in (await db.execute(select(Team).where(Team.id.in_(team_ids)))).scalars().all()
        }

    group = [
        GroupProfilePrediction(
            match_id=str(match.id),
            stage=match.stage.value,
            kickoff_utc=match.kickoff_utc.isoformat() + "Z",
            home_team_name=_team_name(teams.get(match.home_team_id), match.home_team_placeholder),
            away_team_name=_team_name(teams.get(match.away_team_id), match.away_team_placeholder),
            home_team_flag=(t.flag_emoji if (t := teams.get(match.home_team_id)) else None),
            away_team_flag=(t.flag_emoji if (t := teams.get(match.away_team_id)) else None),
            actual_home=match.actual_home_score,
            actual_away=match.actual_away_score,
            predicted_home=pred.predicted_home,
            predicted_away=pred.predicted_away,
            points_awarded=pred.points_awarded,
            points_breakdown=pred.points_breakdown,
        )
        for pred, match in group_rows
    ]

    knockout = [
        KnockoutProfilePrediction(
            match_id=str(match.id),
            stage=match.stage.value,
            kickoff_utc=match.kickoff_utc.isoformat() + "Z",
            home_team_name=_team_name(teams.get(match.home_team_id), match.home_team_placeholder),
            away_team_name=_team_name(teams.get(match.away_team_id), match.away_team_placeholder),
            home_team_flag=(t.flag_emoji if (t := teams.get(match.home_team_id)) else None),
            away_team_flag=(t.flag_emoji if (t := teams.get(match.away_team_id)) else None),
            predicted_winner_id=(
                str(kpred.predicted_winner_id) if kpred.predicted_winner_id else None
            ),
            predicted_winner_name=(w.name if (w := teams.get(kpred.predicted_winner_id)) else None)
            if kpred.predicted_winner_id
            else None,
            points_awarded=kpred.points_awarded,
        )
        for kpred, match in ko_rows
    ]

    specials = [
        SpecialProfilePrediction(
            prediction_type=spred.prediction_type.value,
            predicted_team_id=str(spred.predicted_team_id) if spred.predicted_team_id else None,
            predicted_team_name=(tm.name if (tm := teams.get(spred.predicted_team_id)) else None)
            if spred.predicted_team_id
            else None,
            predicted_player_name=spred.predicted_player_name,
            points_awarded=spred.points_awarded,
        )
        for spred in special_rows
    ]

    return ProfilePredictionsResponse(
        specials_revealed=specials_open,
        group=group,
        knockout=knockout,
        specials=specials,
    )
