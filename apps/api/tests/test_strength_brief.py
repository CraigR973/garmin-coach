"""Tests for Batch 19 strength watching-brief engine.

Covers the four acceptance pillars:
  19.1 — strength-session classification from ``exclude_from_recovery`` (#49)
  19.2 — deterministic frequency / volume / load rollups over rolling windows
  19.3 — DB service and the standalone GET endpoint (DB-backed, skipped without DB)
  19.4 — recovery-isolation invariant: strength sessions never alter the
          Green/Amber/Red verdict or recovery decisions
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from src.models.coaching import Activity
from src.models.profile import Profile, UserRole
from src.services.strength_brief import (
    RECENT_SESSIONS_MAX,
    WINDOW_4W_DAYS,
    WINDOW_12W_DAYS,
    StrengthBriefService,
    StrengthSession,
    compute_strength_rollup,
    is_strength_activity,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TODAY = date(2026, 6, 23)


def _day(offset: int = 0) -> date:
    return TODAY - timedelta(days=offset)


def _session(
    offset_days: int = 0,
    duration_min: int = 45,
    training_load: float = 15.0,
    activity_type: str = "strength_training",
) -> StrengthSession:
    return StrengthSession(
        activity_id=uuid.uuid4(),
        activity_name="Strength Training",
        activity_type=activity_type,
        session_date=_day(offset_days),
        duration_min=duration_min,
        training_load=training_load,
    )


# ---------------------------------------------------------------------------
# 19.1 — Strength-session classification (pure, no DB)
# ---------------------------------------------------------------------------


@dataclass
class _FakeActivity:
    exclude_from_recovery: bool


def test_is_strength_activity_true_when_excluded() -> None:
    """Strength flag correctly identifies excluded activities."""
    act = _FakeActivity(exclude_from_recovery=True)
    assert is_strength_activity(act) is True  # type: ignore[arg-type]


def test_is_strength_activity_false_for_cycling() -> None:
    """Cycling activities (not excluded) are not classified as strength."""
    act = _FakeActivity(exclude_from_recovery=False)
    assert is_strength_activity(act) is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 19.2 — Rollup engine (pure functions, no DB)
# ---------------------------------------------------------------------------


def test_rollup_empty_sessions() -> None:
    """Zero sessions → zero counts everywhere, insufficient-data trend."""
    result = compute_strength_rollup([], as_of_date=TODAY)
    assert result.window_4w.session_count == 0
    assert result.window_12w.session_count == 0
    assert result.window_4w.sessions_per_week == 0.0
    assert result.trend == "insufficient_data"
    assert result.recent_sessions == []


def test_rollup_single_session_insufficient_trend() -> None:
    """One session in 4w window → insufficient_data trend."""
    sessions = [_session(offset_days=3)]
    result = compute_strength_rollup(sessions, as_of_date=TODAY)
    assert result.window_4w.session_count == 1
    assert result.trend == "insufficient_data"


def test_rollup_counts_within_window() -> None:
    """Sessions outside the 12w window are excluded."""
    old = _session(offset_days=WINDOW_12W_DAYS + 1)  # just outside
    recent = _session(offset_days=5)
    result = compute_strength_rollup([old, recent], as_of_date=TODAY)
    assert result.window_12w.session_count == 1
    assert result.window_4w.session_count == 1


def test_rollup_4w_excludes_older() -> None:
    """Sessions between 4w and 12w appear in 12w but not 4w."""
    within_12w = _session(offset_days=WINDOW_4W_DAYS + 1)
    within_4w = _session(offset_days=5)
    result = compute_strength_rollup([within_12w, within_4w], as_of_date=TODAY)
    assert result.window_12w.session_count == 2
    assert result.window_4w.session_count == 1


def test_rollup_volume_and_load() -> None:
    """Volume and load proxy sum correctly across sessions."""
    s1 = _session(offset_days=2, duration_min=40, training_load=12.0)
    s2 = _session(offset_days=7, duration_min=50, training_load=18.0)
    result = compute_strength_rollup([s1, s2], as_of_date=TODAY)
    assert result.window_4w.total_duration_min == 90
    assert abs(result.window_4w.total_load_proxy - 30.0) < 0.01


def test_rollup_sessions_per_week() -> None:
    """Session rate calculation is correct for a 28-day window."""
    sessions = [_session(offset_days=d) for d in [3, 7, 14, 21]]
    result = compute_strength_rollup(sessions, as_of_date=TODAY)
    expected = round(4 / 4, 2)  # 4 sessions / 4 weeks
    assert result.window_4w.sessions_per_week == expected


def test_rollup_trend_stable() -> None:
    """Two sessions in each 2-week half → stable trend."""
    sessions = [_session(offset_days=d) for d in [3, 10, 17, 24]]
    result = compute_strength_rollup(sessions, as_of_date=TODAY)
    assert result.trend == "stable"


def test_rollup_trend_increasing() -> None:
    """More sessions in the recent half than the prior half → increasing."""
    prior = [_session(offset_days=d) for d in [24, 22]]  # 2 sessions in prior 2w
    recent = [_session(offset_days=d) for d in [5, 3, 1]]  # 3 sessions in recent 2w
    result = compute_strength_rollup(prior + recent, as_of_date=TODAY)
    assert result.trend == "increasing"


def test_rollup_trend_decreasing() -> None:
    """Fewer sessions in the recent half than prior half → decreasing."""
    prior = [_session(offset_days=d) for d in [24, 22, 20]]  # 3 in prior 2w
    recent = [_session(offset_days=d) for d in [5]]  # 1 in recent 2w
    result = compute_strength_rollup(prior + recent, as_of_date=TODAY)
    assert result.trend == "decreasing"


def test_rollup_recent_sessions_capped() -> None:
    """recent_sessions list is capped at RECENT_SESSIONS_MAX and sorted newest-first."""
    sessions = [_session(offset_days=d) for d in range(1, RECENT_SESSIONS_MAX + 5)]
    result = compute_strength_rollup(sessions, as_of_date=TODAY)
    assert len(result.recent_sessions) == RECENT_SESSIONS_MAX
    for i in range(len(result.recent_sessions) - 1):
        assert result.recent_sessions[i].session_date >= result.recent_sessions[i + 1].session_date


def test_rollup_none_duration_and_load_treated_as_zero() -> None:
    """Sessions with missing duration/load still count toward session_count."""
    s = StrengthSession(
        activity_id=uuid.uuid4(),
        activity_name="Weights",
        activity_type="strength_training",
        session_date=_day(3),
        duration_min=None,
        training_load=None,
    )
    result = compute_strength_rollup([s], as_of_date=TODAY)
    assert result.window_4w.session_count == 1
    assert result.window_4w.total_duration_min == 0
    assert result.window_4w.total_load_proxy == 0.0


# ---------------------------------------------------------------------------
# 19.4 — Recovery-isolation invariant (pure)
# ---------------------------------------------------------------------------


def test_strength_brief_is_read_only_not_in_recovery_chain() -> None:
    """The rollup result contains no verdict/recovery fields.

    This test asserts Decision #49 / #80: the watching brief is advisory-only
    and must never carry verdict, recovery_decision, or similar cycling-recovery
    fields.  The rollup dataclass should have exactly the documented fields.
    """
    sessions = [_session(offset_days=3)]
    result = compute_strength_rollup(sessions, as_of_date=TODAY)

    allowed_attrs = {
        "as_of_date",
        "window_4w",
        "window_12w",
        "recent_sessions",
        "trend",
        "trend_reason",
    }
    actual_attrs = {f.name for f in result.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    assert actual_attrs == allowed_attrs, (
        "StrengthBriefResult must not carry verdict/recovery fields — "
        f"unexpected fields: {actual_attrs - allowed_attrs}"
    )


def test_exclude_from_recovery_flag_never_unset_by_strength_brief() -> None:
    """is_strength_activity only READS exclude_from_recovery, never changes it.

    Builds a real Activity object (no DB needed) and verifies the flag is the
    same after calling is_strength_activity.
    """
    act = Activity(
        user_id=uuid.uuid4(),
        garmin_activity_id=1,
        activity_name="Gym",
        activity_type="strength_training",
        start_utc=datetime(2026, 6, 20, 9, 0),
        exclude_from_recovery=True,
        raw_summary={},
    )
    result = is_strength_activity(act)
    assert result is True
    assert act.exclude_from_recovery is True  # still True — not mutated


# ---------------------------------------------------------------------------
# 19.3 — DB-backed service tests (skip without DATABASE_URL)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_strength_brief_service_empty_history(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="StrengthBriefTestEmpty",
            pin_hash="x" * 60,
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()

        service = StrengthBriefService(session)
        result = await service.brief(player, as_of=TODAY)

    assert result.window_4w.session_count == 0
    assert result.window_12w.session_count == 0
    assert result.trend == "insufficient_data"


@pytest.mark.asyncio
async def test_strength_brief_service_counts_only_excluded_activities(
    db_conn: AsyncConnection,
) -> None:
    """Service counts strength (excluded) activities and ignores cycling ones."""
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="StrengthBriefTestCounts",
            pin_hash="x" * 60,
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()

        # Two strength sessions in 4w window.
        for i, offset in enumerate([3, 10]):
            session.add(
                Activity(
                    user_id=user_id,
                    garmin_activity_id=1000 + i,
                    activity_name="Strength Training",
                    activity_type="strength_training",
                    start_utc=datetime.combine(TODAY - timedelta(days=offset), datetime.min.time()),
                    duration_sec=2700.0,
                    training_load=14.0,
                    exclude_from_recovery=True,
                    raw_summary={},
                )
            )

        # One cycling session — must NOT appear in strength brief.
        session.add(
            Activity(
                user_id=user_id,
                garmin_activity_id=2000,
                activity_name="Indoor Ride",
                activity_type="indoor_cycling",
                start_utc=datetime.combine(TODAY - timedelta(days=5), datetime.min.time()),
                duration_sec=3600.0,
                avg_power_watts=220,
                avg_heart_rate_bpm=140,
                exclude_from_recovery=False,
                raw_summary={},
            )
        )
        await session.flush()

        service = StrengthBriefService(session)
        result = await service.brief(player, as_of=TODAY)

    # Only the two strength sessions should be counted.
    assert result.window_4w.session_count == 2
    assert result.window_12w.session_count == 2
    assert all(s.activity_type == "strength_training" for s in result.recent_sessions)


@pytest.mark.asyncio
async def test_strength_brief_service_ignores_activities_outside_12w_window(
    db_conn: AsyncConnection,
) -> None:
    """Activities older than 12 weeks are excluded from the 12w rollup."""
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="StrengthBriefTestWindow",
            pin_hash="x" * 60,
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()

        # Inside the 12w window.
        session.add(
            Activity(
                user_id=user_id,
                garmin_activity_id=3001,
                activity_name="Strength Training",
                activity_type="strength_training",
                start_utc=datetime.combine(
                    TODAY - timedelta(days=WINDOW_12W_DAYS - 1), datetime.min.time()
                ),
                duration_sec=2700.0,
                exclude_from_recovery=True,
                raw_summary={},
            )
        )
        # Outside the 12w window (exactly one day older than the cutoff).
        session.add(
            Activity(
                user_id=user_id,
                garmin_activity_id=3002,
                activity_name="Old Strength",
                activity_type="strength_training",
                start_utc=datetime.combine(
                    TODAY - timedelta(days=WINDOW_12W_DAYS + 1), datetime.min.time()
                ),
                duration_sec=2700.0,
                exclude_from_recovery=True,
                raw_summary={},
            )
        )
        await session.flush()

        service = StrengthBriefService(session)
        result = await service.brief(player, as_of=TODAY)

    assert result.window_12w.session_count == 1


@pytest.mark.asyncio
async def test_strength_brief_recovery_isolation_invariant(db_conn: AsyncConnection) -> None:
    """19.4 — Strength sessions appear in brief but are NOT surfaced via
    exclude_from_recovery on a cycling activity.  The flag on the cycling
    activity must remain False regardless of how many strength sessions exist.
    """
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="IsolationTest",
            pin_hash="x" * 60,
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()

        strength = Activity(
            user_id=user_id,
            garmin_activity_id=4001,
            activity_name="Weights",
            activity_type="strength_training",
            start_utc=datetime.combine(TODAY - timedelta(days=2), datetime.min.time()),
            duration_sec=2700.0,
            training_load=14.0,
            exclude_from_recovery=True,
            raw_summary={},
        )
        cycling = Activity(
            user_id=user_id,
            garmin_activity_id=4002,
            activity_name="Indoor Ride",
            activity_type="indoor_cycling",
            start_utc=datetime.combine(TODAY - timedelta(days=1), datetime.min.time()),
            duration_sec=3600.0,
            avg_power_watts=220,
            avg_heart_rate_bpm=140,
            exclude_from_recovery=False,
            raw_summary={},
        )
        session.add(strength)
        session.add(cycling)
        await session.flush()

        service = StrengthBriefService(session)
        result = await service.brief(player, as_of=TODAY)

        # Strength session appears in the brief.
        assert result.window_4w.session_count == 1

        # The cycling activity's exclusion flag is untouched.
        await session.refresh(cycling)
        assert cycling.exclude_from_recovery is False
