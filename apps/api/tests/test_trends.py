"""Tests for Batch 21 year-on-year & seasonal trends.

Covers the four acceptance pillars:
  21.1 — deterministic windowing with reliability cutoffs (#45) (pure + DB)
  21.2 — year-on-year deltas + graceful insufficient-history (pure + DB)
  21.3 — read-only service surface: previews never write (#71)
  21.4 — optional narrative via the Batch 20 boundary, fakeable without a key
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import Analysis, DailyMetric, Sleep
from src.models.profile import Profile, UserRole
from src.services.reviews import ClaudeReviewResult
from src.services.trends import (
    ANALYSIS_TYPE_SEASONAL,
    BUCKET_MONTH,
    BUCKET_SEASON,
    MIN_YOY_SAMPLES,
    RELIABILITY_START_DATE,
    TrendSample,
    TrendsService,
    compute_trend_windows,
    compute_year_on_year,
    prior_year_key,
    season_of,
    window_key,
    window_label,
    window_start_date,
)

# A summer day; history "now".
AS_OF = date(2026, 7, 15)


# ---------------------------------------------------------------------------
# Window keys / labels (pure)
# ---------------------------------------------------------------------------


def test_season_of_rolls_december_into_next_winter() -> None:
    assert season_of(date(2025, 12, 20)) == (2026, "winter")
    assert season_of(date(2026, 1, 5)) == (2026, "winter")
    assert season_of(date(2026, 6, 15)) == (2026, "summer")


def test_window_key_and_label() -> None:
    assert window_key(BUCKET_MONTH, date(2026, 7, 1)) == "2026-07"
    assert window_label(BUCKET_MONTH, "2026-07") == "July 2026"
    assert window_key(BUCKET_SEASON, date(2026, 7, 1)) == "2026-summer"
    assert window_label(BUCKET_SEASON, "2026-summer") == "Summer 2026"


def test_window_start_date_canonical() -> None:
    assert window_start_date(BUCKET_MONTH, "2026-07") == date(2026, 7, 1)
    assert window_start_date(BUCKET_SEASON, "2026-summer") == date(2026, 6, 1)
    # Winter starts in the prior December.
    assert window_start_date(BUCKET_SEASON, "2026-winter") == date(2025, 12, 1)


def test_prior_year_key() -> None:
    assert prior_year_key(BUCKET_MONTH, "2026-07") == "2025-07"
    assert prior_year_key(BUCKET_SEASON, "2026-summer") == "2025-summer"


def test_unknown_bucket_raises() -> None:
    with pytest.raises(ValueError, match="bucket"):
        window_key("weekly", AS_OF)


# ---------------------------------------------------------------------------
# Windowing (pure)
# ---------------------------------------------------------------------------


def test_windows_group_by_month_with_summary_stats() -> None:
    samples = [
        TrendSample(day=date(2026, 6, 10), sleep_score=70, readiness_score=60),
        TrendSample(day=date(2026, 6, 20), sleep_score=80, readiness_score=64),
        TrendSample(day=date(2026, 7, 5), sleep_score=90, readiness_score=70),
    ]
    windows = compute_trend_windows(samples, bucket=BUCKET_MONTH)
    assert [w.key for w in windows] == ["2026-06", "2026-07"]

    june = windows[0]
    sleep = june.metrics["sleep_score"]
    assert sleep.sample_count == 2
    assert sleep.mean == pytest.approx(75.0)
    assert sleep.median == pytest.approx(75.0)
    assert sleep.min == 70 and sleep.max == 80
    assert june.sample_days == 2
    assert june.start == date(2026, 6, 10)
    assert june.end == date(2026, 6, 20)


def test_windows_respect_spo2_hrv_reliability_cutoff() -> None:
    # One night before the cutoff, two after — the gated metrics drop the early one.
    before = RELIABILITY_START_DATE - timedelta(days=2)
    after1 = RELIABILITY_START_DATE
    after2 = RELIABILITY_START_DATE + timedelta(days=1)
    samples = [
        TrendSample(day=before, hrv_ms=40.0, avg_spo2_pct=88.0, sleep_score=60),
        TrendSample(day=after1, hrv_ms=50.0, avg_spo2_pct=94.0, sleep_score=70),
        TrendSample(day=after2, hrv_ms=60.0, avg_spo2_pct=96.0, sleep_score=80),
    ]
    windows = compute_trend_windows(samples, bucket=BUCKET_MONTH)
    assert len(windows) == 1
    hrv = windows[0].metrics["hrv_ms"]
    assert hrv.sample_count == 2  # the pre-cutoff night excluded
    assert hrv.excluded_count == 1
    assert hrv.mean == pytest.approx(55.0)
    # Non-gated metrics keep every night.
    assert windows[0].metrics["sleep_score"].sample_count == 3
    assert windows[0].metrics["sleep_score"].excluded_count == 0


# ---------------------------------------------------------------------------
# Year-on-year (pure)
# ---------------------------------------------------------------------------


def _year_pair_samples() -> list[TrendSample]:
    """5+ nights in the same month across two consecutive years."""
    samples: list[TrendSample] = []
    for i in range(6):
        samples.append(TrendSample(day=date(2025, 7, 1 + i), sleep_score=60, readiness_score=55))
        samples.append(TrendSample(day=date(2026, 7, 1 + i), sleep_score=72, readiness_score=63))
    return samples


def test_year_on_year_computes_same_period_deltas() -> None:
    windows = compute_trend_windows(_year_pair_samples(), bucket=BUCKET_MONTH)
    comparison = compute_year_on_year(windows, bucket=BUCKET_MONTH, target_key="2026-07")

    assert comparison.status == "ok"
    assert comparison.prior_key == "2025-07"
    sleep = next(m for m in comparison.metrics if m.metric_key == "sleep_score")
    assert sleep.status == "ok"
    assert sleep.current_mean == pytest.approx(72.0)
    assert sleep.prior_mean == pytest.approx(60.0)
    assert sleep.delta == pytest.approx(12.0)
    assert sleep.pct_change == pytest.approx(0.2)


def test_year_on_year_insufficient_history_when_no_prior_year() -> None:
    # Only the current year exists — degrade gracefully, no misleading numbers.
    samples = [TrendSample(day=date(2026, 7, 1 + i), sleep_score=70) for i in range(6)]
    windows = compute_trend_windows(samples, bucket=BUCKET_MONTH)
    comparison = compute_year_on_year(windows, bucket=BUCKET_MONTH, target_key="2026-07")

    assert comparison.status == "insufficient_history"
    assert comparison.reasons  # explains why
    sleep = next(m for m in comparison.metrics if m.metric_key == "sleep_score")
    assert sleep.status == "insufficient_history"
    assert sleep.delta is None
    assert sleep.current_mean == pytest.approx(70.0)
    assert sleep.prior_mean is None


def test_year_on_year_requires_min_samples_each_side() -> None:
    # Prior year has only a couple of nights — below MIN_YOY_SAMPLES.
    samples = [TrendSample(day=date(2026, 7, 1 + i), sleep_score=72) for i in range(6)]
    samples += [TrendSample(day=date(2025, 7, 1 + i), sleep_score=60) for i in range(2)]
    assert 2 < MIN_YOY_SAMPLES
    windows = compute_trend_windows(samples, bucket=BUCKET_MONTH)
    comparison = compute_year_on_year(windows, bucket=BUCKET_MONTH, target_key="2026-07")
    assert comparison.status == "insufficient_history"


def test_year_on_year_no_current_data() -> None:
    windows = compute_trend_windows(
        [TrendSample(day=date(2025, 7, 1), sleep_score=60)], bucket=BUCKET_MONTH
    )
    comparison = compute_year_on_year(windows, bucket=BUCKET_MONTH, target_key="2026-07")
    assert comparison.status == "no_current_data"
    assert comparison.metrics == []


# ---------------------------------------------------------------------------
# Narrative boundary fake (no ANTHROPIC_API_KEY needed)
# ---------------------------------------------------------------------------


class FakeReviewClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def generate(
        self, *, context_packet: dict[str, Any], user_prompt: str
    ) -> ClaudeReviewResult:
        self.calls.append({"packet": context_packet, "prompt": user_prompt})
        return ClaudeReviewResult(
            output_markdown="**Year-on-year**\n- Sleep up vs last year.",
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
                display_name="Trends Test",
                pin_hash="x" * 60,
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
            )
        )
        await session.commit()


async def _seed_two_julys(db_conn: AsyncConnection, user_id: uuid.UUID) -> None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        for year, score, readiness in ((2025, 60, 55), (2026, 72, 63)):
            for i in range(6):
                day = date(year, 7, 1 + i)
                session.add(
                    DailyMetric(
                        user_id=user_id,
                        calendar_date=day,
                        readiness_score=readiness,
                        resting_heart_rate_bpm=50,
                        vo2max=52.0,
                    )
                )
                session.add(
                    Sleep(user_id=user_id, calendar_date=day, score=score, duration_sec=27000)
                )
        await session.commit()


@pytest.mark.asyncio
async def test_seasonal_and_yoy_preview_never_write(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    await _seed_two_julys(db_conn, user_id)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        before = await session.scalar(select(func.count()).select_from(Analysis))

        service = TrendsService(session)
        seasonal = await service.seasonal(user, bucket=BUCKET_MONTH, as_of=AS_OF)
        keys = [w.key for w in seasonal.windows]
        assert "2025-07" in keys and "2026-07" in keys

        comparison = await service.year_on_year(user, bucket=BUCKET_MONTH, as_of=AS_OF)
        assert comparison.status == "ok"
        sleep = next(m for m in comparison.metrics if m.metric_key == "sleep_score")
        assert sleep.delta == pytest.approx(12.0)

        after = await session.scalar(select(func.count()).select_from(Analysis))
        assert after == before  # GET previews never write (#71)


@pytest.mark.asyncio
async def test_narrative_run_generates_and_is_idempotent(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    await _seed_two_julys(db_conn, user_id)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = TrendsService(session)
        client = FakeReviewClient()

        first = await service.narrative_run(user, bucket=BUCKET_MONTH, as_of=AS_OF, client=client)
        assert first.generated is True
        assert first.status == "generated"
        assert first.narrative is not None
        assert first.narrative.analysis_type == ANALYSIS_TYPE_SEASONAL
        assert first.narrative.subject_date == date(2026, 7, 1)

        second = await service.narrative_run(user, bucket=BUCKET_MONTH, as_of=AS_OF, client=client)
        assert second.generated is False
        assert second.status == "existing"
        assert len(client.calls) == 1  # second short-circuits

        count = await session.scalar(
            select(func.count())
            .select_from(Analysis)
            .where(Analysis.analysis_type == ANALYSIS_TYPE_SEASONAL)
        )
        assert count == 1


@pytest.mark.asyncio
async def test_narrative_run_reports_insufficient_history_without_calling_model(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    # Only the current year exists.
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        for i in range(6):
            session.add(Sleep(user_id=user_id, calendar_date=date(2026, 7, 1 + i), score=70))
        await session.commit()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = TrendsService(session)
        client = FakeReviewClient()
        result = await service.narrative_run(user, bucket=BUCKET_MONTH, as_of=AS_OF, client=client)

        assert result.generated is False
        assert result.status == "insufficient_history"
        assert result.narrative is None
        assert client.calls == []  # the model is never called (21.4)

        count = await session.scalar(
            select(func.count())
            .select_from(Analysis)
            .where(Analysis.analysis_type == ANALYSIS_TYPE_SEASONAL)
        )
        assert count == 0
