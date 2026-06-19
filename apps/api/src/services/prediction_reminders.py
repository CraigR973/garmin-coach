"""Query helpers for prediction reminder targeting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from src.models.match import Match, MatchStatus
from src.models.prediction import Prediction
from src.models.profile import Profile


@dataclass(frozen=True)
class UnpredictedDigestTarget:
    player: Profile
    matches: list[Match]


@dataclass(frozen=True)
class PickConfirmationTarget:
    player: Profile
    match: Match
    prediction: Prediction


def _submitted_prediction_join(match_id: UUID | None = None) -> ColumnElement[bool]:
    clauses = [
        Prediction.player_id == Profile.id,
        Prediction.submitted_at.is_not(None),
        Prediction.deleted_at.is_(None),
    ]
    if match_id is None:
        clauses.append(Prediction.match_id == Match.id)
    else:
        clauses.append(Prediction.match_id == match_id)
    return and_(*clauses)


async def active_players_without_submitted_prediction_for_match(
    session: AsyncSession,
    match_id: UUID,
) -> list[Profile]:
    """Return active players without a submitted prediction for ``match_id``."""
    result = await session.execute(
        select(Profile)
        .outerjoin(Prediction, _submitted_prediction_join(match_id))
        .where(
            Profile.deleted_at.is_(None),
            Profile.is_active.is_(True),
            Prediction.id.is_(None),
        )
        .order_by(Profile.display_name)
    )
    return list(result.scalars().all())


async def unpredicted_digest_targets_for_window(
    session: AsyncSession,
    window_start: datetime,
    window_end: datetime,
) -> list[UnpredictedDigestTarget]:
    """Return active players and scheduled matches they have not submitted in a UTC window."""
    result = await session.execute(
        select(Profile, Match)
        .join(Match, true())
        .outerjoin(Prediction, _submitted_prediction_join())
        .where(
            Profile.deleted_at.is_(None),
            Profile.is_active.is_(True),
            Match.status == MatchStatus.scheduled,
            Match.deleted_at.is_(None),
            Match.kickoff_utc >= window_start,
            Match.kickoff_utc < window_end,
            Prediction.id.is_(None),
        )
        .order_by(Profile.display_name, Match.kickoff_utc)
    )

    grouped: dict[UUID, UnpredictedDigestTarget] = {}
    for player, match in result.all():
        target = grouped.get(player.id)
        if target is None:
            target = UnpredictedDigestTarget(player=player, matches=[])
            grouped[player.id] = target
        target.matches.append(match)
    return list(grouped.values())


async def submitted_prediction_targets_for_window(
    session: AsyncSession,
    window_start: datetime,
    window_end: datetime,
) -> list[PickConfirmationTarget]:
    """Return active players' submitted predictions for scheduled matches in a UTC window."""
    result = await session.execute(
        select(Profile, Match, Prediction)
        .join(Prediction, Prediction.player_id == Profile.id)
        .join(Match, Match.id == Prediction.match_id)
        .where(
            Profile.deleted_at.is_(None),
            Profile.is_active.is_(True),
            Match.status == MatchStatus.scheduled,
            Match.deleted_at.is_(None),
            Match.kickoff_utc >= window_start,
            Match.kickoff_utc < window_end,
            Prediction.submitted_at.is_not(None),
            Prediction.deleted_at.is_(None),
        )
        .order_by(Match.kickoff_utc, Profile.display_name)
    )
    return [
        PickConfirmationTarget(player=player, match=match, prediction=prediction)
        for player, match, prediction in result.all()
    ]
