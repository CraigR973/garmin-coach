"""Auto result-fetch job (Phase 5.3).

Runs every 5 minutes (driven by the APScheduler IntervalTrigger registered
in `src.scheduler`), pulls the WC competition feed from football-data.org,
and applies a status delta per match:

* ``FINISHED`` → score + status=completed + result_source=auto (skipped if a
  manual or override result already exists).
* ``IN_PLAY``/``PAUSED``/``SUSPENDED`` → status=live.
* ``POSTPONED`` → status=postponed.
* ``CANCELLED`` → status=cancelled.
* ``TIMED``/``SCHEDULED`` → kickoff drift detection — when the upstream
  ``utcDate`` differs from our ``kickoff_utc`` we update kickoff_utc and
  preserve the original. The periodic ``lock_due_matches`` job picks up
  the new kickoff naturally (no per-match job to re-register).

Each row is taken under a ``SELECT ... FOR UPDATE`` lock so simultaneous
admin manual entry cannot race the sync. The job is idempotent — a second
run with unchanged feed is a no-op because we skip matches where
``result_source IS NOT NULL`` for FINISHED handling and avoid redundant
writes elsewhere.

After any finished result is applied we call
:func:`sync_knockout_bracket` so the next knockout round's seeded
placeholder rows resolve to real teams on this — the tournament's primary,
automatic — path. Without it R16+ fixtures stayed on ``TBD`` until an admin
manually entered a result (only the manual admin paths called it before).
The bracket resolver is idempotent and monotonic, so the call is a cheap
no-op when nothing new has settled.

On three consecutive API failures we write an ``auto_sync_failed``
notification for every admin and an ``audit_log`` row with
``action_type = sync_failed``. The counter resets on the next successful
run.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.config import settings
from src.database import AsyncSessionLocal
from src.models.match import Match, MatchStatus, ResultSource
from src.models.notification import (
    ActionType,
    ActorType,
    AuditLog,
)
from src.models.team import Team, TournamentStage
from src.services.football_data import (
    FDMatch,
    FDMatchStatus,
    FootballDataClient,
    FootballDataError,
)
from src.services.knockout_advancement import sync_knockout_bracket
from src.services.notification_triggers import (
    MatchUpdate,
    notify_auto_sync_failed,
    notify_kickoff_changed,
    notify_match_postponed,
    notify_result_detected,
)

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


_LIVE_STATUSES = {
    FDMatchStatus.IN_PLAY,
    FDMatchStatus.PAUSED,
    FDMatchStatus.SUSPENDED,
}
_SCHEDULED_STATUSES = {FDMatchStatus.SCHEDULED, FDMatchStatus.TIMED}
_FD_STAGE_TO_LOCAL_STAGE = {
    "GROUP_STAGE": TournamentStage.group,
    "LAST_32": TournamentStage.r32,
    "ROUND_OF_32": TournamentStage.r32,
    "PRELIMINARY_ROUND": TournamentStage.r32,
    "LAST_16": TournamentStage.r16,
    "ROUND_OF_16": TournamentStage.r16,
    "QUARTER_FINALS": TournamentStage.qf,
    "SEMI_FINALS": TournamentStage.sf,
    "THIRD_PLACE": TournamentStage.third_place,
    "FINAL": TournamentStage.final,
}

_FAILURE_ALERT_THRESHOLD = 3

# Process-lifetime counter. None means "not yet loaded from DB this process".
# Persists across job invocations within a single process (fast path) and is
# recovered from the audit log after a restart (DB path).
_consecutive_failures: int | None = None


async def _load_consecutive_failures(session: AsyncSession) -> int:
    """Return the current failure count, loading from DB on first call."""
    global _consecutive_failures
    if _consecutive_failures is not None:
        return _consecutive_failures
    # DB recovery: count sync_failed rows since the last sync_triggered row.
    last_success_ts = await session.scalar(
        select(AuditLog.timestamp)
        .where(AuditLog.action_type == ActionType.sync_triggered)
        .order_by(AuditLog.timestamp.desc())
        .limit(1)
    )
    q = select(func.count()).where(AuditLog.action_type == ActionType.sync_failed)
    if last_success_ts is not None:
        q = q.where(AuditLog.timestamp > last_success_ts)
    _consecutive_failures = (await session.scalar(q)) or 0
    return _consecutive_failures


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _strip_tz(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(UTC).replace(tzinfo=None)


# Factory aliases so tests can inject mock clients without touching the real one.
ClientFactory = Callable[[], FootballDataClient]
SessionFactory = async_sessionmaker[AsyncSession]


def _default_client_factory() -> FootballDataClient:
    return FootballDataClient(api_key=settings.football_data_api_key)


async def sync_results(
    session_factory: SessionFactory = AsyncSessionLocal,
    client_factory: ClientFactory = _default_client_factory,
    fetcher: Callable[[FootballDataClient], Awaitable[list[FDMatch]]] | None = None,
) -> int:
    """Run one auto-sync cycle.

    Returns the number of matches that were updated. Failures are logged
    and counted; the function does not re-raise so an APScheduler-driven
    invocation never terminates the scheduler.
    """
    client = client_factory()
    try:
        if fetcher is None:
            response = await client.get_competition_matches()
            fd_matches = response.matches
        else:
            fd_matches = await fetcher(client)
    except FootballDataError as exc:
        await _record_failure(session_factory, str(exc))
        return 0
    finally:
        await client.close()

    updates = 0
    match_updates: list[MatchUpdate] = []
    async with session_factory() as session:
        for fd_match in fd_matches:
            changed, update = await _sync_one_match(session, fd_match)
            if changed:
                updates += 1
            if update:
                match_updates.append(update)
        await session.commit()

        # Dispatch push notifications after commit so leaderboard snapshots
        # (written by the DB scoring trigger) are visible to the session.
        for upd in match_updates:
            try:
                if upd.event_type == "finished":
                    await notify_result_detected(session, upd)
                elif upd.event_type == "postponed":
                    await notify_match_postponed(session, upd)
                elif upd.event_type == "kickoff_changed":
                    await notify_kickoff_changed(session, upd)
            except Exception:
                log.exception(
                    "notify failed",
                    event_type=upd.event_type,
                    match_id=str(upd.match_id),
                )
        if match_updates:
            await session.commit()

        # Resolve seeded knockout placeholders into real teams whenever a
        # result has settled — group results fill the R32, knockout results
        # cascade to the next round. This is the auto path's equivalent of the
        # ``_maybe_resync_knockout`` call the manual admin result endpoints make.
        # Best-effort: bracket resolution must never abort the sync cycle.
        if any(u.event_type == "finished" for u in match_updates):
            try:
                await sync_knockout_bracket(session)
            except Exception:
                log.exception("knockout bracket sync failed")

    global _consecutive_failures
    _consecutive_failures = 0
    log.info("auto sync complete", updated=updates, total=len(fd_matches))

    async with session_factory() as session:
        session.add(
            AuditLog(
                actor_id=None,
                actor_type=ActorType.system,
                action_type=ActionType.sync_triggered,
                target_table="matches",
                target_id=None,
                changes={"updated": updates, "total": len(fd_matches)},
            )
        )
        await session.commit()

    return updates


async def _sync_one_match(
    session: AsyncSession, fd_match: FDMatch
) -> tuple[bool, MatchUpdate | None]:
    """Apply the feed's view of a single match. Returns (changed, MatchUpdate|None)."""
    match = await _resolve_match(session, fd_match)
    if match is None:
        return False, None

    now = _now()
    fd_status = fd_match.status

    def _base(event_type: str, **extra: object) -> MatchUpdate:
        return MatchUpdate(
            event_type=event_type,
            match_id=match.id,
            stage=match.stage.value,
            home_team_id=match.home_team_id,
            away_team_id=match.away_team_id,
            home_placeholder=match.home_team_placeholder,
            away_placeholder=match.away_team_placeholder,
            **extra,  # type: ignore[arg-type]
        )

    if fd_status == FDMatchStatus.FINISHED:
        if _apply_finished(session, match, fd_match, now):
            return True, _base(
                "finished",
                home_score=fd_match.score.fullTime.home,
                away_score=fd_match.score.fullTime.away,
            )
        return False, None

    if fd_status == FDMatchStatus.POSTPONED:
        if _apply_postponed(session, match, now):
            return True, _base("postponed")
        return False, None

    if fd_status == FDMatchStatus.CANCELLED:
        return _apply_cancelled(session, match, now), None

    if fd_status in _LIVE_STATUSES:
        return _apply_live(session, match, now), None

    if fd_status in _SCHEDULED_STATUSES:
        old_kickoff = match.kickoff_utc
        if _apply_kickoff_drift(session, match, fd_match, now):
            return True, _base(
                "kickoff_changed",
                old_kickoff=old_kickoff,
                new_kickoff=match.kickoff_utc,
            )
        return False, None

    return False, None


async def _resolve_match(session: AsyncSession, fd_match: FDMatch) -> Match | None:
    row = await session.execute(
        select(Match)
        .where(
            Match.football_data_match_id == fd_match.id,
            Match.deleted_at.is_(None),
        )
        .with_for_update()
    )
    match = row.scalar_one_or_none()
    if match is not None:
        return match
    return await _resolve_match_by_teams(session, fd_match)


async def _resolve_match_by_teams(session: AsyncSession, fd_match: FDMatch) -> Match | None:
    local_stage = _FD_STAGE_TO_LOCAL_STAGE.get(fd_match.stage)
    home_code = fd_match.homeTeam.tla
    away_code = fd_match.awayTeam.tla
    if local_stage is None or not home_code or not away_code:
        return None

    teams_row = await session.execute(select(Team).where(Team.code.in_([home_code, away_code])))
    teams = {team.code: team for team in teams_row.scalars().all()}
    home_team = teams.get(home_code)
    away_team = teams.get(away_code)
    if home_team is None or away_team is None:
        return None

    _maybe_backfill_team_id(home_team, fd_match.homeTeam.id)
    _maybe_backfill_team_id(away_team, fd_match.awayTeam.id)

    match_row = await session.execute(
        select(Match)
        .where(
            Match.stage == local_stage,
            Match.home_team_id == home_team.id,
            Match.away_team_id == away_team.id,
            Match.deleted_at.is_(None),
        )
        .with_for_update()
    )
    matches = list(match_row.scalars().all())
    if len(matches) != 1:
        if len(matches) > 1:
            log.warning(
                "ambiguous fallback match resolution",
                fd_id=fd_match.id,
                fd_stage=fd_match.stage,
                home_code=home_code,
                away_code=away_code,
                candidate_count=len(matches),
            )
        return None

    match = matches[0]
    _maybe_backfill_match_id(match, fd_match.id)
    return match


def _maybe_backfill_team_id(team: Team, fd_team_id: int | None) -> None:
    if fd_team_id is None:
        return
    if team.football_data_team_id is None:
        team.football_data_team_id = fd_team_id
        return
    if team.football_data_team_id != fd_team_id:
        log.warning(
            "football-data team id mismatch",
            team_code=team.code,
            current=team.football_data_team_id,
            incoming=fd_team_id,
        )


def _maybe_backfill_match_id(match: Match, fd_match_id: int) -> None:
    if match.football_data_match_id is None:
        match.football_data_match_id = fd_match_id
        return
    if match.football_data_match_id != fd_match_id:
        log.warning(
            "football-data match id mismatch",
            match_id=str(match.id),
            match_number=match.match_number,
            current=match.football_data_match_id,
            incoming=fd_match_id,
        )


def _apply_finished(session: AsyncSession, match: Match, fd_match: FDMatch, now: datetime) -> bool:
    # Idempotent: a prior auto/manual/override write owns the result.
    if match.result_source is not None:
        return False

    home = fd_match.score.fullTime.home
    away = fd_match.score.fullTime.away
    if home is None or away is None:
        log.warning("finished match missing score", fd_id=fd_match.id)
        return False

    # Match must be locked/live/completed to accept a result, mirroring
    # the admin manual entry validation in routers.admin.
    if match.status not in {MatchStatus.locked, MatchStatus.live, MatchStatus.completed}:
        log.warning(
            "finished match has unexpected local status",
            fd_id=fd_match.id,
            local_status=match.status,
        )
        return False

    match.actual_home_score = home
    match.actual_away_score = away
    match.extra_time = fd_match.score.duration in {"EXTRA_TIME", "PENALTY_SHOOTOUT"}
    match.penalties = fd_match.score.duration == "PENALTY_SHOOTOUT"
    match.result_source = ResultSource.auto
    match.result_entered_by = None
    match.status = MatchStatus.completed
    match.last_synced_at = now

    session.add(
        AuditLog(
            actor_id=None,
            actor_type=ActorType.system,
            action_type=ActionType.result_auto_fetched,
            target_table="matches",
            target_id=match.id,
            changes={
                "actual_home_score": home,
                "actual_away_score": away,
                "result_source": ResultSource.auto.value,
            },
        )
    )
    return True


def _apply_postponed(session: AsyncSession, match: Match, now: datetime) -> bool:
    if match.status in {MatchStatus.postponed, MatchStatus.completed, MatchStatus.cancelled}:
        # Don't undo a completed match or repeat a postponement.
        match.last_synced_at = now
        return False
    match.status = MatchStatus.postponed
    match.last_synced_at = now
    session.add(
        AuditLog(
            actor_id=None,
            actor_type=ActorType.system,
            action_type=ActionType.match_postponed,
            target_table="matches",
            target_id=match.id,
            changes={"source": "football_data"},
        )
    )
    return True


def _apply_cancelled(session: AsyncSession, match: Match, now: datetime) -> bool:
    if match.status in {MatchStatus.cancelled, MatchStatus.completed}:
        match.last_synced_at = now
        return False
    match.status = MatchStatus.cancelled
    match.last_synced_at = now
    session.add(
        AuditLog(
            actor_id=None,
            actor_type=ActorType.system,
            action_type=ActionType.match_cancelled,
            target_table="matches",
            target_id=match.id,
            changes={"source": "football_data"},
        )
    )
    return True


def _apply_live(session: AsyncSession, match: Match, now: datetime) -> bool:
    if match.status == MatchStatus.live:
        match.last_synced_at = now
        return False
    if match.status not in {MatchStatus.locked, MatchStatus.scheduled}:
        # Already completed/postponed/cancelled — feed must catch up.
        match.last_synced_at = now
        return False
    match.status = MatchStatus.live
    match.last_synced_at = now
    return True


def _apply_kickoff_drift(
    session: AsyncSession, match: Match, fd_match: FDMatch, now: datetime
) -> bool:
    if match.status != MatchStatus.scheduled:
        # We don't shift kickoffs for matches that are already locked/live/etc.
        match.last_synced_at = now
        return False
    new_kickoff = _strip_tz(fd_match.utcDate)
    if new_kickoff == match.kickoff_utc:
        match.last_synced_at = now
        return False

    old_kickoff = match.kickoff_utc
    if match.original_kickoff_utc is None:
        match.original_kickoff_utc = old_kickoff
    match.kickoff_utc = new_kickoff
    match.last_synced_at = now

    session.add(
        AuditLog(
            actor_id=None,
            actor_type=ActorType.system,
            action_type=ActionType.kickoff_changed,
            target_table="matches",
            target_id=match.id,
            changes={
                "old_kickoff_utc": old_kickoff.isoformat(),
                "new_kickoff_utc": new_kickoff.isoformat(),
                "source": "football_data",
            },
        )
    )
    return True


async def _record_failure(session_factory: SessionFactory, reason: str) -> None:
    global _consecutive_failures
    async with session_factory() as session:
        consecutive_failures = await _load_consecutive_failures(session) + 1
        _consecutive_failures = consecutive_failures
        log.warning(
            "auto sync failed",
            consecutive_failures=consecutive_failures,
            reason=reason,
        )

        session.add(
            AuditLog(
                actor_id=None,
                actor_type=ActorType.system,
                action_type=ActionType.sync_failed,
                target_table="matches",
                target_id=None,
                changes={
                    "reason": reason,
                    "consecutive_failures": consecutive_failures,
                },
            )
        )

        if consecutive_failures == _FAILURE_ALERT_THRESHOLD:
            try:
                await notify_auto_sync_failed(session, reason)
            except Exception:
                log.exception("notify_auto_sync_failed failed")

        await session.commit()


def reset_failure_counter() -> None:
    """Test helper — reset the in-process counter to 0."""
    global _consecutive_failures
    _consecutive_failures = 0
