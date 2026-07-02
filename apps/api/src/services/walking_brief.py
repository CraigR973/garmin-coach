"""Walking brief engine (Batch 41).

Read-only deterministic rollup for Garmin walking activities. This mirrors the
Batch 19 strength brief shape: pure window maths plus a thin DB service.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import Activity
from src.models.profile import Profile

WINDOW_4W_DAYS = 28
WINDOW_12W_DAYS = 84
RECENT_SESSIONS_MAX = 10


@dataclass(frozen=True)
class WalkingSession:
    activity_id: uuid.UUID
    activity_name: str
    activity_type: str
    session_date: date
    duration_min: int | None
    distance_m: float | None


@dataclass(frozen=True)
class WalkingWindowStats:
    session_count: int
    total_distance_m: float
    total_duration_min: int
    sessions_per_week: float


@dataclass(frozen=True)
class WalkingBriefResult:
    as_of_date: date
    window_4w: WalkingWindowStats
    window_12w: WalkingWindowStats
    recent_sessions: list[WalkingSession]
    trend: str
    trend_reason: str


def is_walking_activity(activity: Activity) -> bool:
    return (activity.activity_type or "").lower() == "walking"


def _window_stats(sessions: Sequence[WalkingSession], window_days: int) -> WalkingWindowStats:
    session_count = len(sessions)
    total_duration_min = sum(session.duration_min or 0 for session in sessions)
    total_distance_m = sum(session.distance_m or 0.0 for session in sessions)
    weeks = window_days / 7
    return WalkingWindowStats(
        session_count=session_count,
        total_distance_m=round(total_distance_m, 1),
        total_duration_min=total_duration_min,
        sessions_per_week=round(session_count / weeks, 2) if weeks > 0 else 0.0,
    )


def compute_walking_rollup(
    all_sessions: Sequence[WalkingSession],
    *,
    as_of_date: date,
    window_4w_days: int = WINDOW_4W_DAYS,
    window_12w_days: int = WINDOW_12W_DAYS,
) -> WalkingBriefResult:
    cutoff_4w = as_of_date - timedelta(days=window_4w_days)
    cutoff_12w = as_of_date - timedelta(days=window_12w_days)
    mid_point = as_of_date - timedelta(days=window_4w_days // 2)

    sessions_4w = [s for s in all_sessions if cutoff_4w < s.session_date <= as_of_date]
    sessions_12w = [s for s in all_sessions if cutoff_12w < s.session_date <= as_of_date]
    prior_half = [s for s in sessions_4w if s.session_date <= mid_point]
    recent_half = [s for s in sessions_4w if s.session_date > mid_point]

    half_weeks = (window_4w_days / 2) / 7
    if len(sessions_4w) < 2:
        trend = "insufficient_data"
        trend_reason = f"Only {len(sessions_4w)} walk(s) in the last {window_4w_days} days."
    else:
        recent_rate = len(recent_half) / half_weeks
        prior_rate = len(prior_half) / half_weeks
        if prior_rate == 0:
            trend = "increasing" if recent_rate > 0 else "stable"
            trend_reason = (
                f"Walks resuming ({recent_rate:.1f}/wk recent vs none prior)."
                if recent_rate > 0
                else "No walks in either half of the 4-week window."
            )
        else:
            change_pct = (recent_rate - prior_rate) / prior_rate
            if change_pct > 0.25:
                trend = "increasing"
                trend_reason = (
                    f"Recent 2-week rate ({recent_rate:.1f}/wk) up "
                    f"from prior 2-week rate ({prior_rate:.1f}/wk)."
                )
            elif change_pct < -0.25:
                trend = "decreasing"
                trend_reason = (
                    f"Recent 2-week rate ({recent_rate:.1f}/wk) down "
                    f"from prior 2-week rate ({prior_rate:.1f}/wk)."
                )
            else:
                overall_rate = round(len(sessions_4w) / (window_4w_days / 7), 1)
                trend = "stable"
                trend_reason = (
                    f"Frequency holding at ~{overall_rate}/wk over {window_4w_days} days."
                )

    recent_sessions = sorted(sessions_4w, key=lambda s: s.session_date, reverse=True)[
        :RECENT_SESSIONS_MAX
    ]
    return WalkingBriefResult(
        as_of_date=as_of_date,
        window_4w=_window_stats(sessions_4w, window_4w_days),
        window_12w=_window_stats(sessions_12w, window_12w_days),
        recent_sessions=list(recent_sessions),
        trend=trend,
        trend_reason=trend_reason,
    )


class WalkingBriefService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def brief(
        self,
        player: Profile,
        *,
        as_of: date | None = None,
    ) -> WalkingBriefResult:
        end = as_of or date.today()
        start = end - timedelta(days=WINDOW_12W_DAYS)
        lower_bound = datetime(start.year, start.month, start.day, tzinfo=UTC).replace(tzinfo=None)
        rows = (
            (
                await self.session.execute(
                    select(Activity)
                    .where(
                        Activity.user_id == player.id,
                        Activity.activity_type == "walking",
                        Activity.start_utc >= lower_bound,
                    )
                    .order_by(Activity.start_utc.asc())
                )
            )
            .scalars()
            .all()
        )
        sessions = [
            WalkingSession(
                activity_id=row.id,
                activity_name=row.activity_name,
                activity_type=row.activity_type,
                session_date=row.start_utc.date(),
                duration_min=round(row.duration_sec / 60) if row.duration_sec is not None else None,
                distance_m=float(row.distance_m) if row.distance_m is not None else None,
            )
            for row in rows
            if row.start_utc.date() <= end
        ]
        return compute_walking_rollup(sessions, as_of_date=end)
