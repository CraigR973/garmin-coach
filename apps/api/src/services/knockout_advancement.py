"""Knockout advancement service (Phase 7.1).

Computes which 32 teams advance from the 12-group stage to the Round of 32
and creates the 16 R32 match rows. Kickoff times for the new matches are
pulled from football-data.org and assigned in chronological order.

Public surface:

* :data:`BRACKET_R32` — the 16 slot-pair templates used to build R32
  matches. Each slot label refers to a position in the group stage:

    * ``1A``..``1L`` — winners of groups A through L (12 slots)
    * ``2A``..``2L`` — runners-up of groups A through L (12 slots)
    * ``T1``..``T8`` — the eight best third-placed teams, ranked
      across all 12 groups using FIFA tiebreakers (points → GD → GF →
      team code)

  Every slot label is used exactly once, so the 32 advancing teams are
  fully consumed across 16 matches. This default pairing is balanced
  (winners avoid winners, runners-up are spread across the bracket) but
  is not bound to FIFA's eventual official 2026 bracket — admin can
  reshuffle pairings later via per-match admin tools.

* :func:`rank_third_place_teams` — sort the twelve third-placed
  standings rows into a single FIFA-ranked list and return the top
  eight.
* :func:`assign_r32_slots` — apply :data:`BRACKET_R32` to a slot →
  ``TeamStanding`` map and produce the ordered list of (home, away)
  team pairs for the 16 R32 matches.
* :func:`advance_to_r32` — orchestrator. Validates that the group
  stage is complete, computes standings via the same helper used by
  the groups router, fetches kickoff times from football-data.org,
  persists 16 ``Match`` rows + one ``AuditLog`` entry per match.

Since U13 the full 32-match knockout bracket is seeded up front (see
:mod:`src.seed`) and the per-round progression — R32 from final standings,
then R16→Final from settled results — is resolved by the pure
:mod:`src.services.knockout_progression` module. :func:`sync_knockout_bracket`
below is the thin DB layer that loads state, calls that resolver, and writes
resolved teams onto the seeded rows. ``advance_to_r32`` predates the seeded
skeleton and is retained for backward compatibility.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.group import Group
from src.models.match import Match, MatchStatus
from src.models.notification import ActionType, ActorType, AuditLog
from src.models.team import Team, TournamentStage
from src.routers.groups import TeamStanding, _compute_standings
from src.services.football_data import FDMatch
from src.services.knockout_progression import (
    BRACKET_R32,
    R32_FIRST_MATCH_NUMBER,
    MatchOutcome,
    assign_r32_slots,
    rank_third_place_teams,
    resolve_bracket,
)

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Bracket constants
# ---------------------------------------------------------------------------

# football-data.org may report Round of 32 under several labels depending on
# competition layout (48-team tournament had no official label before 2026).
# Accept any of these; tests can supply whichever one the live feed uses.
_FD_R32_STAGE_LABELS = frozenset(
    {
        "LAST_32",
        "ROUND_OF_32",
        "PRELIMINARY_ROUND",
    }
)

# The R32 bracket template (``BRACKET_R32``), the third-place ranking
# (``rank_third_place_teams``) and the slot assignment (``assign_r32_slots``)
# now live in :mod:`src.services.knockout_progression` and are imported above.
# They remain importable from this module for backward compatibility with
# Phase 7.1 callers and tests.


# ---------------------------------------------------------------------------
# DB orchestrator
# ---------------------------------------------------------------------------


async def _load_group_standings(db: AsyncSession) -> dict[str, list[TeamStanding]]:
    groups_r = await db.execute(select(Group).order_by(Group.name))
    groups = list(groups_r.scalars().all())

    teams_r = await db.execute(select(Team))
    all_teams = list(teams_r.scalars().all())
    teams_by_group: dict[uuid.UUID, list[Team]] = {}
    for t in all_teams:
        if t.group_id is None:
            continue
        teams_by_group.setdefault(t.group_id, []).append(t)

    matches_r = await db.execute(
        select(Match).where(
            Match.stage == TournamentStage.group,
            Match.deleted_at.is_(None),
        )
    )
    all_matches = list(matches_r.scalars().all())
    matches_by_group: dict[uuid.UUID, list[Match]] = {}
    for m in all_matches:
        if m.group_id is None:
            continue
        matches_by_group.setdefault(m.group_id, []).append(m)

    out: dict[str, list[TeamStanding]] = {}
    for g in groups:
        teams = teams_by_group.get(g.id, [])
        matches = matches_by_group.get(g.id, [])
        out[g.name] = _compute_standings(teams, matches, g.standings_override)
    return out


def _all_group_matches_complete(group_standings: dict[str, list[TeamStanding]]) -> bool:
    # Each team plays 3 matches in a 4-team group. Every standing row's
    # ``played`` count must equal 3 once the group stage is over.
    for standings in group_standings.values():
        for row in standings:
            if row.played != 3:
                return False
    return True


def _filter_r32_fixtures(fd_matches: list[FDMatch]) -> list[FDMatch]:
    r32 = [m for m in fd_matches if m.stage in _FD_R32_STAGE_LABELS]
    r32.sort(key=lambda m: m.utcDate)
    return r32


async def _r32_match_count(db: AsyncSession) -> int:
    rows = await db.execute(
        select(Match).where(
            Match.stage == TournamentStage.r32,
            Match.deleted_at.is_(None),
        )
    )
    return len(list(rows.scalars().all()))


def _strip_tz(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(UTC).replace(tzinfo=None)


class KnockoutAdvanceError(Exception):
    """Raised when advancement preconditions fail. The endpoint maps
    each subclass to the appropriate HTTP status code."""


class GroupStageIncompleteError(KnockoutAdvanceError):
    pass


class AlreadyAdvancedError(KnockoutAdvanceError):
    pass


class MissingKickoffsError(KnockoutAdvanceError):
    pass


async def advance_to_r32(
    db: AsyncSession,
    admin_id: uuid.UUID,
    fd_fetcher: Callable[[], Awaitable[list[FDMatch]]],
) -> list[Match]:
    """Create the sixteen R32 matches.

    Raises one of the :class:`KnockoutAdvanceError` subclasses if a
    precondition fails. The caller is responsible for translating
    those into HTTP responses.

    The DB session is committed here so the audit and match rows land
    together.
    """
    if await _r32_match_count(db) > 0:
        raise AlreadyAdvancedError("R32 matches already exist")

    group_standings = await _load_group_standings(db)
    if not _all_group_matches_complete(group_standings):
        raise GroupStageIncompleteError("Group stage is not yet complete")

    third_place_ranked = rank_third_place_teams(group_standings)
    slot_to_standing = assign_r32_slots(group_standings, third_place_ranked)

    fd_matches_all = await fd_fetcher()
    fd_r32 = _filter_r32_fixtures(fd_matches_all)
    if len(fd_r32) < len(BRACKET_R32):
        raise MissingKickoffsError(
            f"football-data.org returned only {len(fd_r32)} R32 fixtures; need {len(BRACKET_R32)}"
        )

    # Resolve TeamStanding back to ORM Team rows. We don't reload — the
    # Team objects are still cached on `_compute_standings`'s `stats`
    # map, but its result type strips them. Re-fetch by id in one query.
    needed_ids: set[uuid.UUID] = set()
    for standing in slot_to_standing.values():
        needed_ids.add(uuid.UUID(standing.team_id))
    teams_r = await db.execute(select(Team).where(Team.id.in_(needed_ids)))
    team_by_id = {t.id: t for t in teams_r.scalars().all()}

    created: list[Match] = []
    audits: list[AuditLog] = []
    for idx, (home_slot, away_slot) in enumerate(BRACKET_R32):
        home_standing = slot_to_standing[home_slot]
        away_standing = slot_to_standing[away_slot]
        home_team = team_by_id[uuid.UUID(home_standing.team_id)]
        away_team = team_by_id[uuid.UUID(away_standing.team_id)]
        fd_fixture = fd_r32[idx]

        match = Match(
            stage=TournamentStage.r32,
            group_id=None,
            match_number=R32_FIRST_MATCH_NUMBER + idx,
            home_team_id=home_team.id,
            away_team_id=away_team.id,
            home_team_placeholder=home_slot,
            away_team_placeholder=away_slot,
            kickoff_utc=_strip_tz(fd_fixture.utcDate),
            status=MatchStatus.scheduled,
            result_source=None,
            football_data_match_id=fd_fixture.id,
        )
        db.add(match)
        created.append(match)

        audit = AuditLog(
            actor_id=admin_id,
            actor_type=ActorType.admin,
            action_type=ActionType.knockout_advanced,
            target_table="matches",
            target_id=None,  # match.id is assigned during the flush below
            changes={
                "stage": TournamentStage.r32.value,
                "match_number": match.match_number,
                "home_slot": home_slot,
                "away_slot": away_slot,
                "home_team_id": str(home_team.id),
                "away_team_id": str(away_team.id),
                "home_team_code": home_team.code,
                "away_team_code": away_team.code,
                "kickoff_utc": match.kickoff_utc.isoformat(),
                "football_data_match_id": fd_fixture.id,
            },
        )
        db.add(audit)
        audits.append(audit)

    await db.flush()
    for match, audit in zip(created, audits, strict=True):
        audit.target_id = match.id
    await db.commit()
    log.info(
        "advanced to R32",
        admin_id=str(admin_id),
        matches_created=len(created),
        first_kickoff=created[0].kickoff_utc.isoformat(),
    )
    return created


# ---------------------------------------------------------------------------
# Seeded-skeleton resolution (U13)
# ---------------------------------------------------------------------------


async def _load_ko_outcomes(db: AsyncSession) -> dict[int, MatchOutcome]:
    """Map ``match_number`` → :class:`MatchOutcome` for completed KO matches."""
    rows = await db.execute(
        select(Match).where(
            Match.stage != TournamentStage.group,
            Match.status == MatchStatus.completed,
            Match.deleted_at.is_(None),
        )
    )
    outcomes: dict[int, MatchOutcome] = {}
    for m in rows.scalars().all():
        outcomes[m.match_number] = MatchOutcome(
            home_team_id=m.home_team_id,
            away_team_id=m.away_team_id,
            home_score=m.actual_home_score,
            away_score=m.actual_away_score,
            penalty_winner_id=m.penalty_winner_id,
        )
    return outcomes


async def sync_knockout_bracket(db: AsyncSession) -> int:
    """Resolve seeded knockout placeholders into real teams and persist them.

    Loads the current group standings and every settled knockout result, runs
    the pure :func:`resolve_bracket`, and writes any newly-known home/away team
    ids back onto the pre-seeded knockout match rows. Returns the number of
    rows updated.

    Idempotent and monotonic: a slot is only ever filled (never cleared) and is
    re-written only when the resolved team differs from the stored one, so
    re-running with unchanged state is a no-op. Safe to call after any result
    settles — group results resolve the R32, knockout results cascade to the
    next round.
    """
    group_standings = await _load_group_standings(db)
    outcomes = await _load_ko_outcomes(db)
    resolved = resolve_bracket(group_standings, outcomes)

    rows = await db.execute(
        select(Match).where(
            Match.stage != TournamentStage.group,
            Match.deleted_at.is_(None),
        )
    )
    matches_by_number = {m.match_number: m for m in rows.scalars().all()}

    updated = 0
    for match_number, slots in resolved.items():
        match = matches_by_number.get(match_number)
        if match is None:
            continue
        changed = False
        if slots.home_team_id is not None and match.home_team_id != slots.home_team_id:
            match.home_team_id = slots.home_team_id
            changed = True
        if slots.away_team_id is not None and match.away_team_id != slots.away_team_id:
            match.away_team_id = slots.away_team_id
            changed = True
        if changed:
            updated += 1

    if updated:
        await db.commit()
        log.info("knockout bracket resolved", rows_updated=updated)
    return updated
