"""Strength watching-brief engine (Batch 19).

19.1 Classify strength / non-cycling sessions from already-synced Garmin
     activities, reusing the Batch 8 ``exclude_from_recovery`` flag (Decision
     #49).  No new ingestion — all data comes from the ``activities`` table.

19.2 Compute deterministic frequency / volume / load-proxy rollups over two
     rolling windows (4 weeks, 12 weeks) so the pattern is inspectable and
     unit-testable without a database.

19.3 ``StrengthBriefService.brief`` is the DB wrapper that reads the rows and
     calls the pure functions.  The result is advisory-only.

19.4 Recovery-isolation invariant: this module never touches verdict, recovery
     decision, or morning-analysis state.  The ``exclude_from_recovery`` flag is
     *read* for classification but never *written* or used to feed recovery
     signals — see Decision #49 / #80.
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

# ---------------------------------------------------------------------------
# Rolling window sizes
# ---------------------------------------------------------------------------

WINDOW_4W_DAYS = 28
WINDOW_12W_DAYS = 84
RECENT_SESSIONS_MAX = 10


# ---------------------------------------------------------------------------
# Plain data types (no DB dependency — testable as pure values)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StrengthSession:
    activity_id: uuid.UUID
    activity_name: str
    activity_type: str
    session_date: date
    duration_min: int | None
    training_load: float | None


@dataclass(frozen=True)
class WindowStats:
    """Rollup stats for one rolling window."""

    session_count: int
    total_duration_min: int
    total_load_proxy: float
    sessions_per_week: float


@dataclass(frozen=True)
class StrengthBriefResult:
    as_of_date: date
    window_4w: WindowStats
    window_12w: WindowStats
    recent_sessions: list[StrengthSession]
    trend: str  # "increasing" | "stable" | "decreasing" | "insufficient_data"
    trend_reason: str


# ---------------------------------------------------------------------------
# 19.1 — Strength-session classifier
# ---------------------------------------------------------------------------


def is_strength_activity(activity: Activity) -> bool:
    """Return True when the activity is a strength/non-cycling session.

    Delegates entirely to the stored ``exclude_from_recovery`` flag set during
    Garmin sync (Batch 2/8): if ``"strength"`` appears in the Garmin
    ``activityType.typeKey``, the row is flagged at ingestion time.  Using the
    stored flag keeps this module free of duplicate type-key logic and ensures
    the classification is consistent with the recovery-isolation invariant (#49).
    """
    return bool(activity.exclude_from_recovery)


# ---------------------------------------------------------------------------
# 19.2 — Deterministic rollup engine (pure functions)
# ---------------------------------------------------------------------------


def _window_stats(sessions: Sequence[StrengthSession], window_days: int) -> WindowStats:
    session_count = len(sessions)
    total_duration_min = sum(s.duration_min or 0 for s in sessions)
    total_load_proxy = sum(s.training_load or 0.0 for s in sessions)
    weeks = window_days / 7
    return WindowStats(
        session_count=session_count,
        total_duration_min=total_duration_min,
        total_load_proxy=round(total_load_proxy, 2),
        sessions_per_week=round(session_count / weeks, 2) if weeks > 0 else 0.0,
    )


def compute_strength_rollup(
    all_sessions: Sequence[StrengthSession],
    *,
    as_of_date: date,
    window_4w_days: int = WINDOW_4W_DAYS,
    window_12w_days: int = WINDOW_12W_DAYS,
) -> StrengthBriefResult:
    """Compute rolling frequency / volume / load rollups over two windows.

    Trend is derived by comparing the first-half vs second-half of the 4-week
    window (two 2-week halves).  Takes plain ``StrengthSession`` sequences so
    the function is testable without a database.
    """
    cutoff_4w = as_of_date - timedelta(days=window_4w_days)
    cutoff_12w = as_of_date - timedelta(days=window_12w_days)
    mid_point = as_of_date - timedelta(days=window_4w_days // 2)

    sessions_4w = [s for s in all_sessions if s.session_date > cutoff_4w]
    sessions_12w = [s for s in all_sessions if s.session_date > cutoff_12w]

    prior_half = [s for s in sessions_4w if s.session_date <= mid_point]
    recent_half = [s for s in sessions_4w if s.session_date > mid_point]

    # Trend: compare the two 2-week halves of the 4-week window.
    half_weeks = (window_4w_days / 2) / 7
    if len(sessions_4w) < 2:
        trend = "insufficient_data"
        trend_reason = (
            f"Only {len(sessions_4w)} strength session(s) in the last {window_4w_days} days."
        )
    else:
        recent_rate = len(recent_half) / half_weeks
        prior_rate = len(prior_half) / half_weeks
        if prior_rate == 0:
            if recent_rate > 0:
                trend = "increasing"
                trend_reason = f"Sessions resuming ({recent_rate:.1f}/wk recent vs none prior)."
            else:
                trend = "stable"
                trend_reason = "No sessions in either half of the 4-week window."
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

    return StrengthBriefResult(
        as_of_date=as_of_date,
        window_4w=_window_stats(sessions_4w, window_4w_days),
        window_12w=_window_stats(sessions_12w, window_12w_days),
        recent_sessions=list(recent_sessions),
        trend=trend,
        trend_reason=trend_reason,
    )


# ---------------------------------------------------------------------------
# 19.3 — DB service (thin wrapper over the pure engine)
# ---------------------------------------------------------------------------


class StrengthBriefService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def brief(
        self,
        player: Profile,
        *,
        as_of: date | None = None,
    ) -> StrengthBriefResult:
        """Query the already-synced activities and compute the strength brief.

        Only reads ``activities`` rows where ``exclude_from_recovery=True``.
        Never writes; the result is advisory only and never alters verdict/
        recovery state (Decision #49 / #80).
        """
        end = as_of or date.today()
        start = end - timedelta(days=WINDOW_12W_DAYS)

        rows = (
            (
                await self.session.execute(
                    select(Activity)
                    .where(
                        Activity.user_id == player.id,
                        Activity.exclude_from_recovery.is_(True),
                        Activity.start_utc
                        >= datetime(start.year, start.month, start.day, tzinfo=UTC).replace(
                            tzinfo=None
                        ),
                    )
                    .order_by(Activity.start_utc.asc())
                )
            )
            .scalars()
            .all()
        )

        sessions = [
            StrengthSession(
                activity_id=row.id,
                activity_name=row.activity_name,
                activity_type=row.activity_type,
                session_date=row.start_utc.date(),
                duration_min=(
                    round(row.duration_sec / 60) if row.duration_sec is not None else None
                ),
                training_load=(float(row.training_load) if row.training_load is not None else None),
            )
            for row in rows
            if row.start_utc.date() <= end
        ]

        return compute_strength_rollup(sessions, as_of_date=end)
