"""Tests for the historical Garmin backfill runner.

Pure date-iteration helpers are covered hermetically; the runner is exercised
against a real (test) Postgres with an injected fake Garmin client so the
write/skip/resume/dry-run/isolation behaviour is verified without touching the
network.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.garmin_history_backfill import daily_dates, month_chunks, run_backfill
from src.models.coaching import DailyMetric, Sleep
from src.models.profile import Profile, UserRole
from src.services.garmin_sync import GarminActivityPayloads, GarminDailyPayloads

# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_daily_dates_inclusive() -> None:
    assert daily_dates(date(2025, 6, 24), date(2025, 6, 26)) == [
        date(2025, 6, 24),
        date(2025, 6, 25),
        date(2025, 6, 26),
    ]


def test_daily_dates_single_day() -> None:
    assert daily_dates(date(2025, 6, 24), date(2025, 6, 24)) == [date(2025, 6, 24)]


def test_daily_dates_reversed_is_empty() -> None:
    assert daily_dates(date(2025, 6, 26), date(2025, 6, 24)) == []


def test_month_chunks_spans_months() -> None:
    assert month_chunks(date(2025, 6, 24), date(2025, 8, 3)) == [
        (date(2025, 6, 24), date(2025, 6, 30)),
        (date(2025, 7, 1), date(2025, 7, 31)),
        (date(2025, 8, 1), date(2025, 8, 3)),
    ]


def test_month_chunks_single_partial_month() -> None:
    assert month_chunks(date(2025, 6, 10), date(2025, 6, 20)) == [
        (date(2025, 6, 10), date(2025, 6, 20))
    ]


def test_month_chunks_crosses_year_boundary() -> None:
    assert month_chunks(date(2025, 12, 28), date(2026, 1, 2)) == [
        (date(2025, 12, 28), date(2025, 12, 31)),
        (date(2026, 1, 1), date(2026, 1, 2)),
    ]


def test_month_chunks_reversed_is_empty() -> None:
    assert month_chunks(date(2025, 8, 1), date(2025, 6, 1)) == []


# ---------------------------------------------------------------------------
# Fake Garmin client + seeding
# ---------------------------------------------------------------------------


class FakeGarminClient:
    """Returns deterministic per-day payloads; records calls; can fail on dates."""

    def __init__(self, *, fail_on: set[date] | None = None) -> None:
        self.fail_on = set(fail_on or ())
        self.daily_calls: list[date] = []
        self.activity_calls: list[tuple[date, date, bool]] = []

    def fetch_daily_payloads(
        self, calendar_date: date, lookback_days: int = 7
    ) -> GarminDailyPayloads:
        self.daily_calls.append(calendar_date)
        if calendar_date in self.fail_on:
            raise RuntimeError("429 rate limited")
        iso = calendar_date.isoformat()
        return GarminDailyPayloads(
            training_readiness=[{"calendarDate": iso, "score": 70, "level": "MODERATE"}],
            sleep={
                "dailySleepDTO": {
                    "calendarDate": iso,
                    "sleepScores": {"overall": {"value": 75, "qualifierKey": "GOOD"}},
                    "sleepTimeSeconds": 27000,
                }
            },
            hrv={"hrvSummary": {"lastNightAvg": 50, "status": "BALANCED"}},
            rhr={
                "allMetrics": {
                    "metricsMap": {
                        "WELLNESS_RESTING_HEART_RATE": [{"calendarDate": iso, "value": 45}]
                    }
                }
            },
        )

    def fetch_activity_payloads(
        self, start_date: date, end_date: date, *, include_details: bool = True
    ) -> GarminActivityPayloads:
        self.activity_calls.append((start_date, end_date, include_details))
        return GarminActivityPayloads(summaries=[], details_by_activity_id={})


async def _seed_profile(db_conn: AsyncConnection, user_id: uuid.UUID) -> None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            Profile(
                id=user_id,
                display_name="Backfill Test",
                pin_hash="x" * 60,
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
            )
        )
        await session.commit()


async def _count(db_conn: AsyncConnection, model: type, user_id: uuid.UUID) -> int:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        return (
            await session.execute(
                select(func.count()).select_from(model).where(model.user_id == user_id)
            )
        ).scalar_one()


# ---------------------------------------------------------------------------
# DB-backed runner tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_backfill_writes_rows_then_resumes(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    client = FakeGarminClient()
    start, end = date(2025, 6, 24), date(2025, 6, 26)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        profile = await session.get(Profile, user_id)
        assert profile is not None
        summary = await run_backfill(
            session,
            profile,
            client=client,
            start=start,
            end=end,
            throttle=0.0,
            log_fn=lambda _m: None,
        )

    assert summary.days_total == 3
    assert summary.days_synced == 3
    assert summary.days_skipped == 0
    assert summary.daily_metrics_synced == 3
    assert summary.sleep_synced == 3
    assert len(client.activity_calls) == 1  # single calendar-month chunk
    assert await _count(db_conn, DailyMetric, user_id) == 3
    assert await _count(db_conn, Sleep, user_id) == 3

    # Resume: a second run skips days that already have a daily_metrics row,
    # before fetching, and writes no duplicates.
    client2 = FakeGarminClient()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        profile = await session.get(Profile, user_id)
        assert profile is not None
        summary2 = await run_backfill(
            session,
            profile,
            client=client2,
            start=start,
            end=end,
            throttle=0.0,
            log_fn=lambda _m: None,
        )

    assert summary2.days_skipped == 3
    assert summary2.days_synced == 0
    assert client2.daily_calls == []  # skipped before any fetch
    assert await _count(db_conn, DailyMetric, user_id) == 3  # no duplicates


@pytest.mark.asyncio
async def test_run_backfill_dry_run_writes_nothing(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    client = FakeGarminClient()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        profile = await session.get(Profile, user_id)
        assert profile is not None
        summary = await run_backfill(
            session,
            profile,
            client=client,
            start=date(2025, 6, 24),
            end=date(2025, 6, 25),
            dry_run=True,
            throttle=0.0,
            log_fn=lambda _m: None,
        )

    assert summary.days_synced == 2
    assert summary.daily_metrics_synced == 2
    assert summary.sleep_synced == 2
    assert len(client.daily_calls) == 2  # dry-run still fetches to report coverage
    assert await _count(db_conn, DailyMetric, user_id) == 0  # but writes nothing


@pytest.mark.asyncio
async def test_run_backfill_isolates_a_failed_day(
    db_conn: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("src.garmin_history_backfill._RETRY_DELAY_SEC", 0.0)
    monkeypatch.setattr("src.garmin_history_backfill._RETRY_ATTEMPTS", 2)
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    client = FakeGarminClient(fail_on={date(2025, 6, 25)})

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        profile = await session.get(Profile, user_id)
        assert profile is not None
        summary = await run_backfill(
            session,
            profile,
            client=client,
            start=date(2025, 6, 24),
            end=date(2025, 6, 26),
            throttle=0.0,
            log_fn=lambda _m: None,
        )

    assert summary.days_synced == 2
    assert summary.days_failed == 1
    assert any("2025-06-25" in e for e in summary.errors)
    assert await _count(db_conn, DailyMetric, user_id) == 2  # the other two days still landed
