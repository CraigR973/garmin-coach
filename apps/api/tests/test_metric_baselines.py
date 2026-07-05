"""Tests for DB-history-derived metric baselines (services/metric_baselines.py).

Covers the pure :func:`compute_metric_baselines` core (source threading + the
#45 SpO2/HRV reliability cutoff), the DB-backed
:class:`MetricBaselineBackfillService` (create / idempotent rerun / dry-run /
trailing window / xlsx-source coexistence), and the morning "Metrics vs
Baselines" surfacing invariant — empty baselines fall back gracefully, populated
ones are surfaced.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from src.models.coaching import DailyMetric, MetricBaseline, Sleep
from src.models.profile import Profile, UserRole
from src.services.metric_baselines import (
    DB_HISTORY_SOURCE,
    MetricBaselineBackfillService,
)
from src.services.morning_analysis import _metrics_vs_baselines
from src.services.sleep_history import (
    SPO2_HRV_RELIABLE_FROM,
    BaselineSample,
    compute_metric_baselines,
)

# A row that carries every baseline metric: (date, score, rhr, body_battery, spo2, resp, hrv).
_Row = tuple[date, int, int, int, float, float, int]


def _sample(row: _Row) -> BaselineSample:
    day, score, rhr, body_battery, spo2, resp, hrv = row
    return BaselineSample(
        calendar_date=day,
        values={
            "sleep_score": score,
            "age_adjusted_sleep_score": min(score + 4, 100),
            "resting_heart_rate_bpm": rhr,
            "body_battery_charge": body_battery,
            "average_spo2_pct": spo2,
            "average_respiration": resp,
            "hrv_7_day_avg_ms": hrv,
        },
    )


# --- pure core -------------------------------------------------------------


def test_compute_metric_baselines_threads_source_and_honours_cutoff() -> None:
    samples = [
        _sample((date(2026, 6, 10), 70, 44, 55, 94.0, 11.0, 42)),  # pre-cutoff
        _sample((date(2026, 6, 11), 80, 43, 56, 96.0, 10.5, 45)),
        _sample((date(2026, 6, 12), 78, 42, 57, 98.0, 10.0, 46)),
    ]

    baselines = {
        baseline["metric_key"]: baseline
        for baseline in compute_metric_baselines(samples, source=DB_HISTORY_SOURCE)
    }

    # Source is threaded onto every row (top-level + provenance payload).
    assert all(b["source"] == DB_HISTORY_SOURCE for b in baselines.values())
    assert baselines["sleep_score"]["raw_payload"]["source"] == DB_HISTORY_SOURCE

    # #45: pre-2026-06-11 SpO2/HRV dropped from those metrics only, surfaced as excluded.
    assert baselines["average_spo2_pct"]["reliability_start_date"] == SPO2_HRV_RELIABLE_FROM
    assert baselines["average_spo2_pct"]["sample_count"] == 2
    assert baselines["average_spo2_pct"]["excluded_sample_count"] == 1
    assert baselines["average_spo2_pct"]["mean_value"] == pytest.approx(97.0)
    assert baselines["hrv_7_day_avg_ms"]["sample_count"] == 2
    assert baselines["hrv_7_day_avg_ms"]["excluded_sample_count"] == 1

    # Ungated metrics keep every day.
    assert baselines["sleep_score"]["sample_count"] == 3
    assert baselines["sleep_score"]["excluded_sample_count"] == 0
    assert baselines["sleep_score"]["median_value"] == pytest.approx(78.0)
    assert baselines["resting_heart_rate_bpm"]["min_value"] == pytest.approx(42.0)
    assert baselines["resting_heart_rate_bpm"]["max_value"] == pytest.approx(44.0)


def test_compute_metric_baselines_empty_returns_empty() -> None:
    assert compute_metric_baselines([], source=DB_HISTORY_SOURCE) == []


def test_compute_metric_baselines_skips_all_none_metric() -> None:
    samples = [
        BaselineSample(date(2026, 6, 11), {"sleep_score": 80, "body_battery_charge": None}),
        BaselineSample(date(2026, 6, 12), {"sleep_score": 82, "body_battery_charge": None}),
    ]
    keys = {b["metric_key"] for b in compute_metric_baselines(samples, source=DB_HISTORY_SOURCE)}
    assert "sleep_score" in keys
    assert "body_battery_charge" not in keys


# --- morning surfacing invariant ------------------------------------------


def test_metrics_vs_baselines_empty_is_graceful_kb_fallback() -> None:
    # No baselines -> empty table -> morning analysis uses the static KB bands.
    assert _metrics_vs_baselines(None, None, [], None) == []


def test_metrics_vs_baselines_surfaces_computed_baselines() -> None:
    samples = [
        _sample((date(2026, 6, 11), 70, 44, 55, 96.0, 11.0, 45)),
        _sample((date(2026, 6, 12), 80, 42, 57, 98.0, 10.0, 47)),
    ]
    user_id = uuid.uuid4()
    baselines = [
        MetricBaseline(user_id=user_id, **fields)
        for fields in compute_metric_baselines(samples, source=DB_HISTORY_SOURCE)
    ]
    today_sleep = Sleep(user_id=user_id, calendar_date=date(2026, 6, 13), score=85)
    today_metric = DailyMetric(
        user_id=user_id, calendar_date=date(2026, 6, 13), resting_heart_rate_bpm=41
    )

    rows = _metrics_vs_baselines(today_metric, today_sleep, baselines, 89)
    table = {row["metricKey"]: row for row in rows}

    assert table  # populated, not the empty fallback
    assert table["sleep_score"]["currentValue"] == 85
    # median sleep_score over the two samples = 75 -> delta +10
    assert table["sleep_score"]["deltaVsBaseline"] == pytest.approx(10.0)
    assert table["resting_heart_rate_bpm"]["currentValue"] == 41
    assert table["average_spo2_pct"]["reliabilityStartDate"] == SPO2_HRV_RELIABLE_FROM.isoformat()


# --- DB-backed backfill service -------------------------------------------


def _make_profile() -> Profile:
    return Profile(
        id=uuid.uuid4(),
        display_name="Mark",
        pin_hash="x" * 60,
        role=UserRole.admin,
        timezone="Europe/London",
        is_active=True,
    )


def _date_span(start: date, count: int) -> list[date]:
    return [start + timedelta(days=i) for i in range(count)]


def _seed_day(session: object, user_id: uuid.UUID, day: date) -> None:
    # Deterministic per-day values; every baseline metric is populated.
    score = 70 + (day.day % 10)
    session.add(  # type: ignore[attr-defined]
        Sleep(
            user_id=user_id,
            calendar_date=day,
            score=score,
            age_adjusted_score=min(score + 4, 100),
            average_spo2_pct=95.0 + (day.day % 3),
            average_respiration=11.0,
        )
    )
    session.add(  # type: ignore[attr-defined]
        DailyMetric(
            user_id=user_id,
            calendar_date=day,
            readiness_score=70 + (day.day % 8),
            resting_heart_rate_bpm=44 + (day.day % 4),
            body_battery_charged=50 + (day.day % 5),
            hrv_weekly_avg_ms=42 + (day.day % 6),
        )
    )


_ALL_METRIC_KEYS = {
    "sleep_score",
    "age_adjusted_sleep_score",
    "readiness_score",
    "resting_heart_rate_bpm",
    "body_battery_charge",
    "average_spo2_pct",
    "average_respiration",
    "hrv_7_day_avg_ms",
}


@pytest.mark.asyncio
async def test_rebuild_creates_db_history_baselines_with_cutoff(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    profile = _make_profile()
    # 10 days, 2026-06-05 .. 2026-06-14: six pre-cutoff, four reliable.
    days = _date_span(date(2026, 6, 5), 10)

    async with session_factory() as session:
        session.add(profile)
        await session.flush()
        for day in days:
            _seed_day(session, profile.id, day)
        await session.flush()

        result = await MetricBaselineBackfillService(session).rebuild(profile, window_days=None)

        rows = (
            (
                await session.execute(
                    select(MetricBaseline).where(MetricBaseline.user_id == profile.id)
                )
            )
            .scalars()
            .all()
        )

    by_key = {row.metric_key: row for row in rows}
    assert set(by_key) == _ALL_METRIC_KEYS
    assert all(row.source == DB_HISTORY_SOURCE for row in rows)
    assert result.window_start == date(2026, 6, 5)
    assert result.window_end == date(2026, 6, 14)

    assert by_key["sleep_score"].sample_count == 10
    assert by_key["sleep_score"].excluded_sample_count == 0
    # #45 cutoff: only 2026-06-11..14 reliable, 2026-06-05..10 excluded.
    assert by_key["average_spo2_pct"].sample_count == 4
    assert by_key["average_spo2_pct"].excluded_sample_count == 6
    assert by_key["average_spo2_pct"].reliability_start_date == SPO2_HRV_RELIABLE_FROM
    assert by_key["hrv_7_day_avg_ms"].sample_count == 4
    assert by_key["hrv_7_day_avg_ms"].excluded_sample_count == 6


@pytest.mark.asyncio
async def test_rebuild_is_idempotent(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    profile = _make_profile()
    days = _date_span(date(2026, 6, 11), 5)  # all reliable -> no exclusions

    async with session_factory() as session:
        session.add(profile)
        await session.flush()
        for day in days:
            _seed_day(session, profile.id, day)
        await session.flush()

        service = MetricBaselineBackfillService(session)
        first = await service.rebuild(profile, window_days=None)
        second = await service.rebuild(profile, window_days=None)

        count = len(
            (
                await session.execute(
                    select(MetricBaseline).where(MetricBaseline.user_id == profile.id)
                )
            )
            .scalars()
            .all()
        )

    assert first.baselines_created == len(_ALL_METRIC_KEYS)
    assert first.baselines_updated == 0
    assert second.baselines_created == 0
    assert second.baselines_updated == 0
    assert second.baselines_unchanged == len(_ALL_METRIC_KEYS)
    assert count == len(_ALL_METRIC_KEYS)


@pytest.mark.asyncio
async def test_rebuild_dry_run_writes_nothing(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    profile = _make_profile()
    days = _date_span(date(2026, 6, 11), 4)

    async with session_factory() as session:
        session.add(profile)
        await session.flush()
        for day in days:
            _seed_day(session, profile.id, day)
        await session.flush()

        result = await MetricBaselineBackfillService(session).rebuild(
            profile, window_days=None, dry_run=True
        )

        rows = (
            (
                await session.execute(
                    select(MetricBaseline).where(MetricBaseline.user_id == profile.id)
                )
            )
            .scalars()
            .all()
        )

    assert result.dry_run is True
    assert result.baselines_created == len(_ALL_METRIC_KEYS)
    assert rows == []


@pytest.mark.asyncio
async def test_rebuild_respects_window_days(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    profile = _make_profile()
    days = _date_span(date(2026, 5, 6), 40)  # 2026-05-06 .. 2026-06-14

    async with session_factory() as session:
        session.add(profile)
        await session.flush()
        for day in days:
            _seed_day(session, profile.id, day)
        await session.flush()

        result = await MetricBaselineBackfillService(session).rebuild(
            profile, window_days=10, as_of=date(2026, 6, 14)
        )

        sleep_score = (
            await session.execute(
                select(MetricBaseline).where(
                    MetricBaseline.user_id == profile.id,
                    MetricBaseline.metric_key == "sleep_score",
                )
            )
        ).scalar_one()

    assert result.window_start == date(2026, 6, 5)
    assert result.window_end == date(2026, 6, 14)
    assert result.samples_considered == 10
    assert sleep_score.sample_count == 10


@pytest.mark.asyncio
async def test_rebuild_coexists_with_xlsx_source(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    profile = _make_profile()
    days = _date_span(date(2026, 6, 11), 4)

    async with session_factory() as session:
        session.add(profile)
        await session.flush()
        for day in days:
            _seed_day(session, profile.id, day)
        # A pre-existing xlsx-sourced baseline must survive untouched.
        xlsx_row = MetricBaseline(
            user_id=profile.id,
            metric_key="sleep_score",
            metric_label="Sleep score",
            source="sleep_history_xlsx",
            window_start_date=date(2026, 3, 24),
            window_end_date=date(2026, 6, 15),
            sample_count=84,
            excluded_sample_count=0,
            median_value=72.0,
        )
        session.add(xlsx_row)
        await session.flush()

        await MetricBaselineBackfillService(session).rebuild(profile, window_days=None)

        sleep_score_rows = (
            (
                await session.execute(
                    select(MetricBaseline).where(
                        MetricBaseline.user_id == profile.id,
                        MetricBaseline.metric_key == "sleep_score",
                    )
                )
            )
            .scalars()
            .all()
        )

    by_source = {row.source: row for row in sleep_score_rows}
    assert set(by_source) == {"sleep_history_xlsx", DB_HISTORY_SOURCE}
    # xlsx row untouched.
    assert by_source["sleep_history_xlsx"].median_value == pytest.approx(72.0)
    assert by_source["sleep_history_xlsx"].sample_count == 84
