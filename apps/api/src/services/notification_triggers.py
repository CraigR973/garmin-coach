"""Notification trigger helpers.

Each public function corresponds to one NotificationType and is called
by the subsystem that detects the event (scheduler, result_sync, auth,
specials, admin routers). Functions add NotificationLog rows via
send_notification() but do NOT commit — the caller is responsible.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.models.league import League
from src.models.match import Match, MatchStatus
from src.models.notification import NotificationLog, NotificationType
from src.models.prediction import LeaderboardSnapshot
from src.models.profile import PlayerRole, Profile
from src.models.team import Team
from src.services.prediction_reminders import (
    PickConfirmationTarget,
    active_players_without_submitted_prediction_for_match,
    submitted_prediction_targets_for_window,
    unpredicted_digest_targets_for_window,
)
from src.services.push_notification_service import send_notification

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)
UK_TZ = ZoneInfo("Europe/London")


# ── Data transfer object from sync/scheduler ─────────────────────────────────


@dataclass
class MatchUpdate:
    """Snapshot of a match state captured before commit for notification use."""

    event_type: str  # "finished" | "postponed" | "kickoff_changed"
    match_id: UUID
    stage: str
    home_team_id: UUID | None
    away_team_id: UUID | None
    home_placeholder: str | None
    away_placeholder: str | None
    home_score: int | None = None
    away_score: int | None = None
    old_kickoff: datetime | None = None
    new_kickoff: datetime | None = None
    extra: dict[str, Any] = field(default_factory=dict)


# ── Internal helpers ──────────────────────────────────────────────────────────


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _active_players(session: AsyncSession) -> list[Profile]:
    result = await session.execute(
        select(Profile).where(Profile.deleted_at.is_(None), Profile.is_active.is_(True))
    )
    return list(result.scalars().all())


async def _admin_players(session: AsyncSession) -> list[Profile]:
    result = await session.execute(
        select(Profile).where(
            Profile.role == PlayerRole.admin,
            Profile.deleted_at.is_(None),
        )
    )
    return list(result.scalars().all())


async def _team_name(session: AsyncSession, team_id: UUID | None, placeholder: str | None) -> str:
    if team_id is None:
        return placeholder or "TBD"
    result = await session.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    return team.name if team else (placeholder or "TBD")


async def _match_desc(session: AsyncSession, update: MatchUpdate) -> str:
    home = await _team_name(session, update.home_team_id, update.home_placeholder)
    away = await _team_name(session, update.away_team_id, update.away_placeholder)
    return f"{home} vs {away}"


async def _notify_all(
    session: AsyncSession,
    notification_type: NotificationType,
    title: str,
    body: str,
    match_id: UUID | None = None,
    data: dict[str, Any] | None = None,
    tag: str | None = None,
) -> None:
    players = await _active_players(session)
    for p in players:
        await send_notification(
            session,
            p.id,
            notification_type,
            title,
            body,
            match_id=match_id,
            data=data,
            tag=tag,
        )


# ── Trigger functions ─────────────────────────────────────────────────────────


async def notify_match_locked(session: AsyncSession, update: MatchUpdate) -> None:
    desc = await _match_desc(session, update)
    await _notify_all(
        session,
        NotificationType.match_locked,
        f"⚽ {desc} has kicked off!",
        "Predictions are locked — see what everyone picked 👀",
        match_id=update.match_id,
        data={"url": f"/matches/{update.match_id}"},
        tag=f"match-{update.match_id}",
    )


async def notify_tournament_started(session: AsyncSession) -> None:
    """Fire once when the opening match locks — reveals specials and the global table."""
    await _notify_all(
        session,
        NotificationType.specials_revealed,
        "🏆 The 2026 World Cup has started!",
        "Specials are locked — see how everyone picked and check the global table",
        data={"url": "/predictions/specials"},
        tag="specials",
    )


@dataclass
class _RankMove:
    """One player's rank change in a single league after a result."""

    league: League | None
    old: int
    new: int


def _format_movement(moves: list[_RankMove]) -> tuple[str, str, str]:
    """Build (title, body, deep-link url) for one player's rank change(s).

    A single move names the league and deep-links to its leaderboard; multiple
    leagues moving at once are summarised into one notification pointing at the
    leagues hub, so a player in many leagues gets one push, not a storm.
    """
    if len(moves) == 1:
        move = moves[0]
        name = move.league.name if move.league else "your league"
        slug = move.league.slug if move.league else None
        url = f"/leagues/{slug}/leaderboard" if slug else "/leagues"
        places = abs(move.old - move.new)
        unit = "place" if places == 1 else "places"
        if move.new < move.old:
            return (
                f"📈 Up to #{move.new} in {name}",
                f"You climbed {places} {unit} — was #{move.old}",
                url,
            )
        return (
            f"📉 Down to #{move.new} in {name}",
            f"You slipped {places} {unit} — was #{move.old}",
            url,
        )

    parts: list[str] = []
    for move in moves[:3]:
        name = move.league.name if move.league else "a league"
        arrow = "↑" if move.new < move.old else "↓"
        parts.append(f"{arrow} #{move.new} {name}")
    summary = ", ".join(parts)
    if len(moves) > 3:
        summary += f", +{len(moves) - 3} more"
    return f"Your rank changed in {len(moves)} leagues", summary, "/leagues"


async def notify_result_detected(session: AsyncSession, update: MatchUpdate) -> None:
    home = await _team_name(session, update.home_team_id, update.home_placeholder)
    away = await _team_name(session, update.away_team_id, update.away_placeholder)
    score = f"{update.home_score}–{update.away_score}"
    tag = f"result-{update.match_id}"

    # Personalised rank-move pushes take priority: players who moved get the
    # richer "you climbed to #N in <league>" notification instead of the generic
    # broadcast. They share the result tag so even if both reach a device the
    # move replaces the broadcast rather than stacking.
    moved = await notify_leaderboard_shifts(session, update.match_id, tag=tag)

    for player in await _active_players(session):
        if player.id in moved:
            continue
        await send_notification(
            session,
            player.id,
            NotificationType.result_detected,
            f"Result: {home} {score} {away}",
            "Points are in — see the latest standings",
            match_id=update.match_id,
            data={"url": f"/matches/{update.match_id}"},
            tag=tag,
        )

    await notify_round_complete(session, update.stage)


async def notify_leaderboard_shifts(
    session: AsyncSession, match_id: UUID, tag: str | None = None
) -> set[UUID]:
    """Notify each player whose rank changed after the result for match_id.

    Leaderboards are per-league, so a player in several leagues can move in more
    than one at once. The old code keyed snapshots by player alone, silently
    dropping all but one league and sending an unlabelled "you moved to #N" — so
    a multi-league player couldn't tell which table changed. This groups the
    result's snapshots per league, compares each against that league's previous
    snapshot, and sends ONE notification that names the league(s) and deep-links
    to the leaderboard. Returns the set of notified player ids so the caller can
    suppress the generic result broadcast for them.
    """
    new_snaps_result = await session.execute(
        select(LeaderboardSnapshot).where(LeaderboardSnapshot.triggered_by_match_id == match_id)
    )
    new_snaps = list(new_snaps_result.scalars().all())
    if not new_snaps:
        return set()

    league_ids = {s.league_id for s in new_snaps}
    leagues_result = await session.execute(select(League).where(League.id.in_(league_ids)))
    leagues = {lg.id: lg for lg in leagues_result.scalars().all()}

    snaps_by_player: dict[UUID, list[LeaderboardSnapshot]] = defaultdict(list)
    for snap in new_snaps:
        snaps_by_player[snap.player_id].append(snap)

    moved: set[UUID] = set()
    for player_id, snaps in snaps_by_player.items():
        moves: list[_RankMove] = []
        for snap in snaps:
            prev_result = await session.execute(
                select(LeaderboardSnapshot)
                .where(
                    LeaderboardSnapshot.player_id == player_id,
                    LeaderboardSnapshot.league_id == snap.league_id,
                    LeaderboardSnapshot.triggered_by_match_id != match_id,
                )
                .order_by(LeaderboardSnapshot.snapshot_at.desc())
                .limit(1)
            )
            prev = prev_result.scalar_one_or_none()
            if prev is None or prev.rank == snap.rank:
                continue
            moves.append(
                _RankMove(league=leagues.get(snap.league_id), old=prev.rank, new=snap.rank)
            )

        if not moves:
            continue
        moved.add(player_id)
        title, body, url = _format_movement(moves)
        await send_notification(
            session,
            player_id,
            NotificationType.leaderboard_shift,
            title,
            body,
            data={"url": url},
            tag=tag,
        )

    return moved


async def notify_round_complete(session: AsyncSession, stage: str) -> None:
    """Send round_complete when every non-cancelled match in a stage is finished."""
    total_result = await session.execute(
        select(func.count())
        .select_from(Match)
        .where(
            Match.stage == stage,
            Match.deleted_at.is_(None),
            Match.status != MatchStatus.cancelled,
        )
    )
    total = total_result.scalar() or 0

    done_result = await session.execute(
        select(func.count())
        .select_from(Match)
        .where(
            Match.stage == stage,
            Match.deleted_at.is_(None),
            Match.status == MatchStatus.completed,
        )
    )
    done = done_result.scalar() or 0

    if total > 0 and done >= total:
        stage_label = stage.replace("_", " ").title()
        await _notify_all(
            session,
            NotificationType.round_complete,
            f"🏁 {stage_label} complete",
            "Final standings and points for this round are in — check the leaderboard!",
            data={"url": "/leagues"},
            tag=f"round-{stage}",
        )


async def notify_match_postponed(session: AsyncSession, update: MatchUpdate) -> None:
    desc = await _match_desc(session, update)
    await _notify_all(
        session,
        NotificationType.match_postponed,
        f"⏸️ {desc} postponed",
        f"{desc} has been postponed — your prediction is safe until it's rescheduled",
        match_id=update.match_id,
        data={"url": f"/matches/{update.match_id}"},
        tag=f"match-{update.match_id}",
    )


async def notify_kickoff_changed(session: AsyncSession, update: MatchUpdate) -> None:
    desc = await _match_desc(session, update)
    if update.new_kickoff:
        new_str = update.new_kickoff.strftime("%d %b, %H:%M UTC")
        body = f"{desc} now kicks off {new_str}"
    else:
        body = f"Kickoff time changed for {desc}"
    await _notify_all(
        session,
        NotificationType.kickoff_changed,
        f"⏰ Kickoff moved: {desc}",
        body,
        match_id=update.match_id,
        data={"url": f"/matches/{update.match_id}"},
        tag=f"match-{update.match_id}",
    )


async def notify_invite_accepted(
    session: AsyncSession,
    new_player_name: str,
) -> None:
    """Notify admins when a brand-new player signs up via invite."""
    admins = await _admin_players(session)
    for admin in admins:
        await send_notification(
            session,
            admin.id,
            NotificationType.invite_accepted,
            "New player joined",
            f"{new_player_name} has joined the league!",
        )


async def notify_member_joined(
    session: AsyncSession,
    player_name: str,
    league_name: str,
) -> None:
    """Notify admins when an existing player joins a league via code or invite."""
    admins = await _admin_players(session)
    for admin in admins:
        await send_notification(
            session,
            admin.id,
            NotificationType.member_joined,
            f"New member: {league_name}",
            f"{player_name} has joined {league_name}.",
        )


async def notify_special_results_awarded(
    session: AsyncSession,
    prediction_type: str,
) -> None:
    label = prediction_type.replace("_", " ").title()
    await _notify_all(
        session,
        NotificationType.special_results,
        "Special predictions scored",
        f"{label} predictions have been awarded — check your points!",
        data={"url": "/predictions/specials"},
        tag="specials",
    )


async def notify_auto_sync_failed(session: AsyncSession, reason: str) -> None:
    """Push alert to admins on consecutive sync failure (replaces bare log)."""
    admins = await _admin_players(session)
    for admin in admins:
        await send_notification(
            session,
            admin.id,
            NotificationType.auto_sync_failed,
            "Result auto-sync is failing",
            f"Last error: {reason[:200]}",
        )


async def notify_backup_failed(session: AsyncSession, reason: str) -> None:
    """Push alert to admins when the scheduled backup job fails."""
    admins = await _admin_players(session)
    for admin in admins:
        await send_notification(
            session,
            admin.id,
            NotificationType.auto_sync_failed,
            "Scheduled backup failed",
            f"Error: {reason[:200]}",
        )


# ── Deadline warning scheduler job ───────────────────────────────────────────

# Module-level set keyed by (match_id, warning_minutes) so the 60-min and
# 15-min jobs each get their own bucket and neither suppresses the other.
_warned_match_ids: set[tuple[UUID, int]] = set()
_evening_warned: set[tuple[UUID, UUID]] = set()


async def check_deadline_warnings(
    session_factory: async_sessionmaker[AsyncSession],
    now: datetime | None = None,
    warning_minutes: int = 15,
    unpredicted_only: bool = False,
) -> int:
    """Warn players N minutes before each scheduled match kickoff.

    When unpredicted_only=True, only players without a submitted prediction receive the push.
    Returns the number of matches warned. Called every minute by the scheduler.
    """
    current = (now if now is not None else _utc_now()).replace(second=0, microsecond=0)

    window_start = current + timedelta(minutes=warning_minutes - 1)
    window_end = current + timedelta(minutes=warning_minutes + 1)

    warned = 0
    async with session_factory() as session:
        result = await session.execute(
            select(Match).where(
                Match.status == MatchStatus.scheduled,
                Match.kickoff_utc >= window_start,
                Match.kickoff_utc < window_end,
                Match.deleted_at.is_(None),
            )
        )
        matches = list(result.scalars().all())

        for match in matches:
            if (match.id, warning_minutes) in _warned_match_ids:
                continue
            _warned_match_ids.add((match.id, warning_minutes))
            home = await _team_name(session, match.home_team_id, match.home_team_placeholder)
            away = await _team_name(session, match.away_team_id, match.away_team_placeholder)
            desc = f"{home} vs {away}"
            title = f"{warning_minutes} min to go: {desc}"
            body = "Submit your prediction before kickoff!"
            if unpredicted_only:
                players = await active_players_without_submitted_prediction_for_match(
                    session, match.id
                )
                for player in players:
                    await send_notification(
                        session,
                        player.id,
                        NotificationType.deadline_warning,
                        title,
                        body,
                        match_id=match.id,
                        data={"url": "/predictions"},
                        tag=f"predict-{match.id}",
                    )
            else:
                await _notify_all(
                    session,
                    NotificationType.deadline_warning,
                    title,
                    body,
                    match_id=match.id,
                    data={"url": "/predictions"},
                    tag=f"predict-{match.id}",
                )
            warned += 1

        if warned:
            await session.commit()
            log.info("deadline warnings sent", count=warned, unpredicted_only=unpredicted_only)

    return warned


async def check_evening_kickoff_warnings(
    session_factory: async_sessionmaker[AsyncSession],
    now: datetime | None = None,
) -> int:
    """At 21:00 UK time, send a heads-up for matches kicking off 22:00–10:00 UK tonight/tomorrow.

    Players with a prediction get their score and a reminder they can still edit.
    Players without a prediction get a prompt to predict before kickoff.
    """
    current = (now if now is not None else _utc_now()).replace(second=0, microsecond=0)
    current_uk = current.replace(tzinfo=UTC).astimezone(UK_TZ)
    if not (current_uk.hour == 21 and current_uk.minute == 0):
        return 0

    today_uk = current_uk.date()
    window_start_utc = (
        datetime.combine(today_uk, time(22, 0), tzinfo=UK_TZ).astimezone(UTC).replace(tzinfo=None)
    )
    window_end_utc = (
        datetime.combine(today_uk + timedelta(days=1), time(10, 0), tzinfo=UK_TZ)
        .astimezone(UTC)
        .replace(tzinfo=None)
    )
    today_start_utc = datetime.combine(current.date(), time.min)

    sent = 0
    async with session_factory() as session:
        # ── Players WITH a prediction ─────────────────────────────────────────
        predicted_targets = await submitted_prediction_targets_for_window(
            session, window_start_utc, window_end_utc
        )
        for target in predicted_targets:
            key = (target.match.id, target.player.id)
            if key in _evening_warned:
                continue
            already = await session.scalar(
                select(func.count()).where(
                    NotificationLog.notification_type == NotificationType.predict_reminder,
                    NotificationLog.match_id == target.match.id,
                    NotificationLog.player_id == target.player.id,
                    NotificationLog.sent_at >= today_start_utc,
                )
            )
            if already:
                _evening_warned.add(key)
                continue
            home = await _team_name(
                session, target.match.home_team_id, target.match.home_team_placeholder
            )
            away = await _team_name(
                session, target.match.away_team_id, target.match.away_team_placeholder
            )
            kickoff_str = (
                target.match.kickoff_utc.replace(tzinfo=UTC).astimezone(UK_TZ).strftime("%H:%M %Z")
            )
            score = f"{target.prediction.predicted_home}–{target.prediction.predicted_away}"
            await send_notification(
                session,
                target.player.id,
                NotificationType.predict_reminder,
                f"{home} v {away} — kicks off {kickoff_str}",
                f"You've predicted {score}. You can still edit.",
                match_id=target.match.id,
                data={"url": "/predictions"},
                tag=f"predict-{target.match.id}",
            )
            _evening_warned.add(key)
            sent += 1

        # ── Players WITHOUT a prediction ──────────────────────────────────────
        matches_result = await session.execute(
            select(Match).where(
                Match.status == MatchStatus.scheduled,
                Match.kickoff_utc >= window_start_utc,
                Match.kickoff_utc < window_end_utc,
                Match.deleted_at.is_(None),
            )
        )
        for match in matches_result.scalars().all():
            home = await _team_name(session, match.home_team_id, match.home_team_placeholder)
            away = await _team_name(session, match.away_team_id, match.away_team_placeholder)
            kickoff_str = (
                match.kickoff_utc.replace(tzinfo=UTC).astimezone(UK_TZ).strftime("%H:%M %Z")
            )
            unpredicted = await active_players_without_submitted_prediction_for_match(
                session, match.id
            )
            for player in unpredicted:
                key = (match.id, player.id)
                if key in _evening_warned:
                    continue
                already = await session.scalar(
                    select(func.count()).where(
                        NotificationLog.notification_type == NotificationType.predict_reminder,
                        NotificationLog.match_id == match.id,
                        NotificationLog.player_id == player.id,
                        NotificationLog.sent_at >= today_start_utc,
                    )
                )
                if already:
                    _evening_warned.add(key)
                    continue
                await send_notification(
                    session,
                    player.id,
                    NotificationType.predict_reminder,
                    f"{home} v {away} — kicks off {kickoff_str}",
                    "Predict before kickoff!",
                    match_id=match.id,
                    data={"url": "/predictions"},
                    tag=f"predict-{match.id}",
                )
                _evening_warned.add(key)
                sent += 1

        if sent:
            await session.commit()
            log.info("evening kickoff warnings sent", count=sent)

    return sent


# ── Prediction reminder scheduler jobs ───────────────────────────────────────


def _player_day_window(player: Profile, current: datetime) -> tuple[datetime, datetime]:
    try:
        tz = ZoneInfo(player.timezone)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")
    local_now = current.replace(tzinfo=UTC).astimezone(tz)
    local_start = datetime.combine(local_now.date(), time.min, tzinfo=tz)
    local_end = local_start + timedelta(days=1)
    return (
        local_start.astimezone(UTC).replace(tzinfo=None),
        local_end.astimezone(UTC).replace(tzinfo=None),
    )


async def send_daily_prediction_digest(
    session_factory: async_sessionmaker[AsyncSession],
    now: datetime | None = None,
) -> int:
    """Send one same-day unpredicted-match digest per targeted active player."""
    current = now if now is not None else _utc_now()
    sent_targets = 0

    async with session_factory() as session:
        players = await _active_players(session)
        players_by_window: dict[tuple[datetime, datetime], set[UUID]] = {}
        for player in players:
            window = _player_day_window(player, current)
            players_by_window.setdefault(window, set()).add(player.id)

        for (window_start, window_end), player_ids in players_by_window.items():
            targets = await unpredicted_digest_targets_for_window(
                session,
                window_start,
                window_end,
            )
            for target in targets:
                if target.player.id not in player_ids:
                    continue
                count = len(target.matches)
                body = (
                    "You have 1 match to predict today"
                    if count == 1
                    else f"You have {count} matches to predict today"
                )
                await send_notification(
                    session,
                    target.player.id,
                    NotificationType.predict_reminder,
                    "Prediction reminder",
                    body,
                    data={"url": "/predictions"},
                    tag="daily-digest",
                )
                sent_targets += 1

        if sent_targets:
            await session.commit()
            log.info("daily prediction digests sent", count=sent_targets)

    return sent_targets


async def check_pick_confirmations(
    session_factory: async_sessionmaker[AsyncSession],
    now: datetime | None = None,
    warning_minutes: int = 15,
) -> int:
    """Send opt-in per-match pick confirmations before kickoff."""
    current = (now if now is not None else _utc_now()).replace(second=0, microsecond=0)
    window_start = current + timedelta(minutes=warning_minutes - 1)
    window_end = current + timedelta(minutes=warning_minutes + 1)

    sent_targets = 0
    async with session_factory() as session:
        targets = await submitted_prediction_targets_for_window(session, window_start, window_end)
        for target in targets:
            # Check the NotificationLog (DB-backed) so dedup survives restarts.
            already_sent = await session.scalar(
                select(func.count()).where(
                    NotificationLog.notification_type == NotificationType.pick_confirmation,
                    NotificationLog.match_id == target.match.id,
                    NotificationLog.player_id == target.player.id,
                )
            )
            if already_sent:
                continue
            await _send_pick_confirmation(session, target)
            sent_targets += 1

        if sent_targets:
            await session.commit()
            log.info("pick confirmations sent", count=sent_targets)

    return sent_targets


async def _send_pick_confirmation(session: AsyncSession, target: PickConfirmationTarget) -> None:
    home = await _team_name(
        session,
        target.match.home_team_id,
        target.match.home_team_placeholder,
    )
    away = await _team_name(
        session,
        target.match.away_team_id,
        target.match.away_team_placeholder,
    )
    score = f"{target.prediction.predicted_home}–{target.prediction.predicted_away}"
    kickoff = target.match.kickoff_utc.strftime("%H:%M UTC")
    await send_notification(
        session,
        target.player.id,
        NotificationType.pick_confirmation,
        f"Your pick for {home} v {away}",
        f"{score} · kicks off {kickoff}",
        data={"url": "/predictions"},
        match_id=target.match.id,
        tag=f"predict-{target.match.id}",
    )
