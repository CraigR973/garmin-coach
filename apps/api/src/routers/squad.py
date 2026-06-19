"""Squad player search endpoint (U14.3).

GET /api/v1/squad/search?q=<query>&limit=<n>

Public (no auth required) — same precedent as GET /leagues/by-code/{code}.
Rate-limited to 120/minute per IP.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import case, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.squad import SquadPlayer
from src.models.team import Team
from src.rate_limit import limiter

router = APIRouter(prefix="/api/v1/squad", tags=["squad"])

_MAX_LIMIT = 30


class SquadPlayerResult:
    """Lightweight result DTO — returned as plain dicts for speed."""


@router.get("/search")
@limiter.limit("120/minute")
async def search_squad(
    request: Request,  # required by slowapi
    db: Annotated[AsyncSession, Depends(get_db)],
    q: str = Query(default="", max_length=100),
    limit: int = Query(default=20, ge=1, le=_MAX_LIMIT),
    position: str | None = Query(default=None, max_length=10),
) -> list[dict[str, Any]]:
    """Case-insensitive substring search across full_name and known_as.

    Returns players ranked: exact known_as prefix first, then full_name prefix,
    then any substring match — all alphabetical within each tier.

    Optional ``position`` filter (e.g. ``GK``) restricts results to that
    position — used by the Golden Glove picker.
    """
    q = q.strip()
    if not q:
        return []

    q_lower = q.lower()

    # unaccent() strips diacritics on both sides so "martinez" matches
    # "Martínez", "Rodriguez" matches "Rodríguez", etc.
    ua_full = func.unaccent(func.lower(SquadPlayer.full_name))
    ua_known = func.unaccent(func.lower(SquadPlayer.known_as))
    ua_q_lit = func.unaccent(func.lower(literal(q_lower)))
    ua_like = func.concat(literal("%"), ua_q_lit, literal("%"))
    ua_prefix = func.concat(ua_q_lit, literal("%"))

    conditions = [
        SquadPlayer.is_active.is_(True),
        or_(
            ua_full.like(ua_like),
            ua_known.like(ua_like),
        ),
    ]
    if position is not None:
        conditions.append(SquadPlayer.position == position.upper())

    stmt = (
        select(
            SquadPlayer.id,
            SquadPlayer.full_name,
            SquadPlayer.known_as,
            SquadPlayer.position,
            SquadPlayer.shirt_number,
            Team.code.label("team_code"),
            Team.name.label("team_name"),
            Team.flag_emoji,
        )
        .join(Team, SquadPlayer.team_id == Team.id)
        .where(*conditions)
        # Rank: known_as prefix match → full_name prefix match → substring
        .order_by(
            case(
                (ua_known.like(ua_prefix), 0),
                (ua_full.like(ua_prefix), 1),
                else_=2,
            ),
            SquadPlayer.full_name,
        )
        .limit(limit)
    )

    rows = (await db.execute(stmt)).all()

    return [
        {
            "id": str(row.id),
            "full_name": row.full_name,
            "known_as": row.known_as,
            "position": row.position,
            "shirt_number": row.shirt_number,
            "team_code": row.team_code,
            "team_name": row.team_name,
            "flag_emoji": row.flag_emoji,
        }
        for row in rows
    ]
