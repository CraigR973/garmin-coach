"""Tests for Batch 20 weekly & monthly deep reviews.

Covers the four acceptance pillars:
  20.1 — deterministic rollup packet assembly (pure + DB-backed)
  20.2 — Claude review boundary, fakeable without ``ANTHROPIC_API_KEY``
  20.3 — monthly variant shares the rollup + boundary, wider window
  20.4 — human/API-triggered: previews never write, ``run`` is idempotent (#71)
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import (
    Activity,
    Analysis,
    DailyMetric,
    KnowledgeBase,
    MetricBaseline,
    PlannedWorkout,
    Sleep,
)
from src.models.profile import Profile, UserRole
from src.services.reviews import (
    ANALYSIS_TYPE_MONTHLY,
    ANALYSIS_TYPE_WEEKLY,
    PERIOD_MONTHLY,
    PERIOD_WEEKLY,
    ClaudeReviewResult,
    ReviewActivity,
    ReviewAdherence,
    ReviewDay,
    ReviewService,
    ReviewThermalNight,
    compute_review_rollup,
    resolve_period_window,
)

# A Wednesday, so the ISO week is Mon 2026-06-22 .. Sun 2026-06-28.
AS_OF = date(2026, 6, 24)
WEEK_START = date(2026, 6, 22)
WEEK_END = date(2026, 6, 28)


# ---------------------------------------------------------------------------
# Period windows (pure)
# ---------------------------------------------------------------------------


def test_resolve_weekly_window_is_iso_week() -> None:
    start, end = resolve_period_window(PERIOD_WEEKLY, AS_OF)
    assert start == WEEK_START
    assert end == WEEK_END
    assert start.weekday() == 0  # Monday


def test_resolve_monthly_window_is_calendar_month() -> None:
    start, end = resolve_period_window(PERIOD_MONTHLY, date(2026, 6, 15))
    assert start == date(2026, 6, 1)
    assert end == date(2026, 6, 30)


def test_resolve_monthly_window_handles_december_rollover() -> None:
    start, end = resolve_period_window(PERIOD_MONTHLY, date(2026, 12, 10))
    assert start == date(2026, 12, 1)
    assert end == date(2026, 12, 31)


def test_resolve_unknown_period_raises() -> None:
    with pytest.raises(ValueError, match="period"):
        resolve_period_window("daily", AS_OF)


# ---------------------------------------------------------------------------
# Rollup aggregation (pure)
# ---------------------------------------------------------------------------


def _rollup(days: list[ReviewDay], **kwargs: Any):
    return compute_review_rollup(
        days,
        kwargs.pop("activities", []),
        kwargs.pop("adherence", []),
        kwargs.pop("thermal", []),
        period=PERIOD_WEEKLY,
        period_start=WEEK_START,
        period_end=WEEK_END,
        planned_count=kwargs.pop("planned_count", 0),
        **kwargs,
    )


def test_rollup_averages_sleep_and_recovery() -> None:
    days = [
        ReviewDay(day=WEEK_START + timedelta(days=i), sleep_score=70 + i, readiness_score=60 + i)
        for i in range(4)
    ]
    rollup = _rollup(days)
    assert rollup.sleep.nights == 4
    assert rollup.sleep.avg_score == pytest.approx(71.5)
    assert rollup.recovery.avg_readiness == pytest.approx(61.5)
    assert rollup.day_count == 7


def test_rollup_counts_verdicts_case_insensitive() -> None:
    days = [
        ReviewDay(day=WEEK_START, verdict="Green"),
        ReviewDay(day=WEEK_START + timedelta(days=1), verdict="amber"),
        ReviewDay(day=WEEK_START + timedelta(days=2), verdict="RED"),
        ReviewDay(day=WEEK_START + timedelta(days=3), verdict=None),
    ]
    rollup = _rollup(days)
    assert (rollup.verdicts.green, rollup.verdicts.amber, rollup.verdicts.red) == (1, 1, 1)
    assert rollup.verdicts.total == 3


def test_rollup_sums_load_by_type() -> None:
    activities = [
        ReviewActivity(
            day=WEEK_START, activity_type="cycling", duration_min=60, training_load=80.0
        ),
        ReviewActivity(
            day=WEEK_START + timedelta(days=1),
            activity_type="cycling",
            duration_min=45,
            training_load=50.0,
        ),
        ReviewActivity(
            day=WEEK_START + timedelta(days=2),
            activity_type="strength_training",
            duration_min=30,
            training_load=15.0,
        ),
    ]
    rollup = _rollup([], activities=activities)
    assert rollup.training_load.activity_count == 3
    assert rollup.training_load.total_load == pytest.approx(145.0)
    assert rollup.training_load.total_duration_min == 135
    assert rollup.training_load.by_type == {"cycling": 130.0, "strength_training": 15.0}


def test_rollup_adherence_counts_only_captured() -> None:
    adherence = [
        ReviewAdherence(day=WEEK_START, status="completed"),
        ReviewAdherence(day=WEEK_START + timedelta(days=1), status="modified"),
        ReviewAdherence(day=WEEK_START + timedelta(days=2), status="completed"),
        ReviewAdherence(day=WEEK_START + timedelta(days=3), status=None),
    ]
    rollup = _rollup([], adherence=adherence, planned_count=5)
    assert rollup.adherence.planned_count == 5
    assert rollup.adherence.captured_count == 3
    assert rollup.adherence.status_counts == {"completed": 2, "modified": 1}


def test_rollup_flags_thermal_disruption_nights() -> None:
    thermal = [
        ReviewThermalNight(day=WEEK_START, indoor_peak_c=18.0, overnight_low_c=8.0),
        ReviewThermalNight(
            day=WEEK_START + timedelta(days=1), indoor_peak_c=21.0, overnight_low_c=9.0
        ),
        ReviewThermalNight(
            day=WEEK_START + timedelta(days=2), indoor_peak_c=20.0, overnight_low_c=10.0
        ),
    ]
    rollup = _rollup([], thermal=thermal)
    assert rollup.thermal.nights == 3
    assert rollup.thermal.disruption_nights == 2  # 21.0 and 20.0 both >= 20.0
    assert rollup.thermal.avg_indoor_peak_c == pytest.approx(19.7, abs=0.05)


def test_rollup_trend_increasing_and_insufficient() -> None:
    rising = [
        ReviewDay(day=WEEK_START + timedelta(days=i), sleep_score=score)
        for i, score in enumerate([60, 62, 61, 80, 82, 81])
    ]
    assert _rollup(rising).sleep.trend == "increasing"

    sparse = [ReviewDay(day=WEEK_START, sleep_score=70)]
    assert _rollup(sparse).sleep.trend == "insufficient_data"


def test_readiness_trend_treats_four_point_move_as_stable_noise() -> None:
    days = [
        ReviewDay(day=WEEK_START + timedelta(days=i), readiness_score=score)
        for i, score in enumerate([80, 80, 80, 76, 76, 76])
    ]

    assert _rollup(days).recovery.trend == "stable"


# ---------------------------------------------------------------------------
# Claude review boundary fake (no ANTHROPIC_API_KEY needed)
# ---------------------------------------------------------------------------


class FakeReviewClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def generate(
        self, *, context_packet: dict[str, Any], user_prompt: str
    ) -> ClaudeReviewResult:
        self.calls.append({"packet": context_packet, "prompt": user_prompt})
        period = context_packet.get("period")
        return ClaudeReviewResult(
            output_markdown=f"**Trends**\n- {period} review narrative.",
            raw_response={"id": "fake", "model": "fake-model"},
            model_name="fake-model",
        )


# ---------------------------------------------------------------------------
# DB-backed service tests
# ---------------------------------------------------------------------------


async def _seed_profile(db_conn: AsyncConnection, user_id: uuid.UUID) -> None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            Profile(
                id=user_id,
                display_name="Reviews Test",
                pin_hash="x" * 60,
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
            )
        )
        await session.commit()


async def _seed_week(db_conn: AsyncConnection, user_id: uuid.UUID) -> None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        for i in range(7):
            day = WEEK_START + timedelta(days=i)
            session.add(
                DailyMetric(
                    user_id=user_id,
                    calendar_date=day,
                    hrv_last_night_avg_ms=50 + i,
                    readiness_score=60 + i,
                    resting_heart_rate_bpm=48,
                    body_battery_charged=70,
                )
            )
            session.add(Sleep(user_id=user_id, calendar_date=day, score=70 + i, duration_sec=27000))
            session.add(
                Analysis(
                    user_id=user_id,
                    analysis_type="morning",
                    subject_date=day,
                    generated_at_utc=datetime(2026, 6, 22, 6, 30) + timedelta(days=i),
                    prompt_version="morning-x",
                    verdict="Green" if i % 2 == 0 else "Amber",
                    context_packet={},
                    output_markdown="x",
                    raw_response={},
                )
            )
        session.add(
            Activity(
                id=uuid.uuid4(),
                user_id=user_id,
                garmin_activity_id=5001,
                activity_name="Ride",
                activity_type="cycling",
                start_utc=datetime(2026, 6, 23, 17, 0),
                duration_sec=3600,
                training_load=80.0,
            )
        )
        session.add(
            PlannedWorkout(
                user_id=user_id,
                workout_date=WEEK_START + timedelta(days=1),
                version=1,
                title="VO2",
                workout_type="vo2",
                is_active=True,
            )
        )
        session.add(
            MetricBaseline(
                user_id=user_id,
                metric_key="readiness_score",
                metric_label="Training readiness",
                source="test",
                window_start_date=date(2026, 4, 1),
                window_end_date=date(2026, 6, 30),
                sample_count=84,
                excluded_sample_count=0,
                mean_value=76,
                median_value=76,
                lower_quartile_value=72,
                upper_quartile_value=82,
                raw_payload={},
            )
        )
        session.add(
            KnowledgeBase(
                user_id=user_id,
                section="training_schedule",
                version=1,
                is_active=True,
                source="test",
                content={"restDays": ["Monday", "Friday"], "longRideDay": "Saturday"},
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_preview_assembles_rollup_and_never_writes(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    await _seed_week(db_conn, user_id)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        before = await session.scalar(select(func.count()).select_from(Analysis))

        service = ReviewService(session)
        preview = await service.preview(user, PERIOD_WEEKLY, as_of=AS_OF)

        assert preview.period_start == WEEK_START
        assert preview.period_end == WEEK_END
        assert preview.rollup.sleep.nights == 7
        assert preview.rollup.recovery.days == 7
        assert preview.rollup.training_load.activity_count == 1
        assert preview.rollup.training_load.by_type == {"cycling": 80.0}
        assert preview.rollup.verdicts.green == 4
        assert preview.rollup.verdicts.amber == 3
        assert preview.latest_review is None
        # The packet carries the strength brief + insights for the narrative.
        assert "strengthBrief" in preview.packet
        assert "ftpDrift" in preview.packet["insights"]
        assert preview.packet["personalBaselines"]["readiness_score"]["mean"] == 76
        assert preview.packet["trainingSchedule"]["restDays"] == ["Monday", "Friday"]

        # GET preview must not write an analyses row (#71).
        after = await session.scalar(select(func.count()).select_from(Analysis))
        assert after == before


@pytest.mark.asyncio
async def test_run_generates_and_stores_weekly_review(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    await _seed_week(db_conn, user_id)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ReviewService(session)
        client = FakeReviewClient()
        result = await service.run(user, PERIOD_WEEKLY, as_of=AS_OF, client=client)

        assert result.generated is True
        assert result.review.analysis_type == ANALYSIS_TYPE_WEEKLY
        assert result.review.subject_date == WEEK_START
        assert result.review.model_name == "fake-model"
        assert "narrative" in result.review.output_markdown
        assert len(client.calls) == 1

        stored = (
            (
                await session.execute(
                    select(Analysis).where(Analysis.analysis_type == ANALYSIS_TYPE_WEEKLY)
                )
            )
            .scalars()
            .all()
        )
        assert len(stored) == 1


@pytest.mark.asyncio
async def test_run_is_idempotent_per_period(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    await _seed_week(db_conn, user_id)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ReviewService(session)
        client = FakeReviewClient()

        first = await service.run(user, PERIOD_WEEKLY, as_of=AS_OF, client=client)
        second = await service.run(user, PERIOD_WEEKLY, as_of=AS_OF, client=client)

        assert first.generated is True
        assert second.generated is False
        assert len(client.calls) == 1  # the second call short-circuits

        count = await session.scalar(
            select(func.count())
            .select_from(Analysis)
            .where(Analysis.analysis_type == ANALYSIS_TYPE_WEEKLY)
        )
        assert count == 1


@pytest.mark.asyncio
async def test_monthly_run_uses_monthly_window_and_type(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    await _seed_week(db_conn, user_id)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ReviewService(session)
        result = await service.run(user, PERIOD_MONTHLY, as_of=AS_OF, client=FakeReviewClient())

        assert result.review.analysis_type == ANALYSIS_TYPE_MONTHLY
        assert result.review.subject_date == date(2026, 6, 1)
        assert result.preview.period_end == date(2026, 6, 30)
        # The 7 seeded days all fall inside June, so the monthly rollup sees them.
        assert result.preview.rollup.sleep.nights == 7
