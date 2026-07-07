"""Tests for Batch 17 monitoring + insight engines.

Covers the four acceptance pillars that live here: FTP-drift detection (17.1),
early-warning alert thresholds (17.2), correlation computation (17.3), and the
audit-recording ``run`` path. The experiment lifecycle (17.4) is in
``test_experiment_tracker.py``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import (
    Activity,
    Analysis,
    DailyMetric,
    FanStateReading,
    Sleep,
    TemperatureReading,
    WeatherDaily,
)
from src.models.profile import Profile, UserRole
from src.services.insights import (
    AUDIT_TYPE_DRIVERS,
    AUDIT_TYPE_EARLY_WARNING,
    AUDIT_TYPE_FTP_DRIFT,
    DRIVER_KEYS,
    OUTCOME_RECOVERY_HRV,
    OUTCOME_SLEEP_SCORE,
    DriverCorrelation,
    DriversReport,
    InsightsService,
    PowerHrSample,
    TrendDay,
    _drivers_packet,
    _drivers_report_from_packet,
    compute_drivers,
    detect_early_warning,
    detect_ftp_drift,
    pearson,
)

D0 = date(2026, 5, 1)


def _day(n: int) -> date:
    return D0 + timedelta(days=n)


# ---------------------------------------------------------------------------
# 17.1 — FTP drift (pure)
# ---------------------------------------------------------------------------


def _sample(n: int, power: float, hr: float) -> PowerHrSample:
    return PowerHrSample(
        activity_date=_day(n),
        avg_power_watts=power,
        normalized_power_watts=None,
        avg_heart_rate_bpm=hr,
    )


def test_ftp_drift_insufficient_data() -> None:
    result = detect_ftp_drift([_sample(0, 200, 140), _sample(1, 205, 140)], current_ftp_watts=280)
    assert result.status == "insufficient_data"
    assert result.sample_count == 2
    assert result.suggested_ftp_watts is None


def test_ftp_drift_rising_surfaces_evidence_window() -> None:
    # Earlier rides EF ~1.43; recent rides EF ~1.57 → +10% efficiency.
    samples = [
        _sample(0, 200, 140),
        _sample(2, 200, 140),
        _sample(10, 220, 140),
        _sample(14, 220, 140),
    ]
    result = detect_ftp_drift(samples, current_ftp_watts=280)
    assert result.status == "rising"
    assert result.sample_count == 4
    # Evidence window is surfaced.
    assert result.window_start == _day(0)
    assert result.window_end == _day(14)
    assert result.pct_change is not None and result.pct_change > 0.03
    assert result.suggested_ftp_watts == round(280 * (1 + result.pct_change))


def test_ftp_drift_falling() -> None:
    samples = [
        _sample(0, 220, 140),
        _sample(2, 220, 140),
        _sample(10, 200, 140),
        _sample(14, 200, 140),
    ]
    result = detect_ftp_drift(samples, current_ftp_watts=280)
    assert result.status == "falling"
    assert result.suggested_ftp_watts is not None and result.suggested_ftp_watts < 280


def test_ftp_drift_stable_within_threshold() -> None:
    samples = [
        _sample(0, 200, 140),
        _sample(2, 201, 140),
        _sample(10, 202, 140),
        _sample(14, 203, 140),
    ]
    result = detect_ftp_drift(samples, current_ftp_watts=280)
    assert result.status == "stable"
    assert result.suggested_ftp_watts is None


def test_ftp_drift_ignores_samples_without_hr() -> None:
    samples = [
        PowerHrSample(_day(0), 200, None, None),  # no HR → excluded
        _sample(1, 200, 140),
        _sample(2, 200, 140),
    ]
    result = detect_ftp_drift(samples, current_ftp_watts=280)
    # Only two valid samples remain → insufficient.
    assert result.status == "insufficient_data"
    assert result.sample_count == 2


# ---------------------------------------------------------------------------
# 17.2 — Early warning (pure)
# ---------------------------------------------------------------------------


def test_early_warning_insufficient_data() -> None:
    result = detect_early_warning(
        [TrendDay(_day(0), 55, 80, 70, None), TrendDay(_day(1), 54, 79, 69, None)]
    )
    assert result.status == "insufficient_data"
    assert result.fired is False


def test_early_warning_fires_on_two_degrading_trends_before_red() -> None:
    days = [
        TrendDay(_day(0), 55.0, 80.0, 70.0, "Green"),
        TrendDay(_day(1), 53.0, 76.0, 68.0, "Green"),
        TrendDay(_day(2), 51.0, 72.0, 66.0, "Amber"),
        TrendDay(_day(3), 49.0, 68.0, 64.0, "Amber"),
    ]
    result = detect_early_warning(days)
    assert result.status == "early_warning"
    assert result.fired is True
    assert set(result.degrading_metrics) >= {"hrv", "sleep"}


def test_early_warning_watch_on_single_degrading_trend() -> None:
    days = [
        TrendDay(_day(0), 55.0, 80.0, 70.0, "Green"),
        TrendDay(_day(1), 53.0, 80.0, 70.0, "Green"),
        TrendDay(_day(2), 51.0, 80.0, 70.0, "Green"),
        TrendDay(_day(3), 49.0, 80.0, 70.0, "Green"),
    ]
    result = detect_early_warning(days)
    assert result.status == "watch"
    assert result.fired is False
    assert result.degrading_metrics == ["hrv"]


def test_early_warning_already_red_is_not_early() -> None:
    days = [
        TrendDay(_day(0), 55.0, 80.0, 70.0, "Green"),
        TrendDay(_day(1), 53.0, 76.0, 68.0, "Amber"),
        TrendDay(_day(2), 51.0, 72.0, 66.0, "Red"),
        TrendDay(_day(3), 49.0, 68.0, 64.0, "Red"),
    ]
    result = detect_early_warning(days)
    assert result.status == "already_red"
    assert result.fired is False


def test_early_warning_ok_when_stable() -> None:
    days = [
        TrendDay(_day(0), 55.0, 80.0, 70.0, "Green"),
        TrendDay(_day(1), 55.0, 81.0, 71.0, "Green"),
        TrendDay(_day(2), 56.0, 80.0, 70.0, "Green"),
        TrendDay(_day(3), 56.0, 82.0, 72.0, "Green"),
    ]
    result = detect_early_warning(days)
    assert result.status == "ok"
    assert result.fired is False


# ---------------------------------------------------------------------------
# 17.3 — Driver/correlation (pure)
# ---------------------------------------------------------------------------


def test_pearson_perfect_positive() -> None:
    assert pearson([1, 2, 3, 4], [2, 4, 6, 8]) == pytest.approx(1.0)


def test_pearson_zero_variance_is_none() -> None:
    assert pearson([1, 1, 1, 1], [1, 2, 3, 4]) is None


def test_compute_drivers_ranks_by_absolute_correlation() -> None:
    records: list[dict[str, float | None]] = []
    for i in range(10):
        records.append(
            {
                OUTCOME_SLEEP_SCORE: float(80 - i),  # decreasing
                "overnight_low_c": float(i),  # perfectly negatively correlated
                "daytime_stress_avg": float(40 + (i % 2)),  # near-flat / weak
                "resting_heart_rate_bpm": None,  # missing → skipped
            }
        )
    drivers = compute_drivers(
        records,
        outcome_key=OUTCOME_SLEEP_SCORE,
        driver_keys=("overnight_low_c", "daytime_stress_avg", "resting_heart_rate_bpm"),
    )
    names = [d.driver for d in drivers]
    assert "resting_heart_rate_bpm" not in names  # too few samples
    assert names[0] == "overnight_low_c"  # strongest mover ranked first
    assert drivers[0].direction == "negative"
    assert drivers[0].coefficient == pytest.approx(-1.0)


def test_compute_drivers_skips_below_min_samples() -> None:
    records: list[dict[str, float | None]] = [
        {OUTCOME_SLEEP_SCORE: float(i), "overnight_low_c": float(i)} for i in range(3)
    ]
    drivers = compute_drivers(
        records, outcome_key=OUTCOME_SLEEP_SCORE, driver_keys=("overnight_low_c",)
    )
    assert drivers == []


def test_compute_drivers_adds_plain_language_bedroom_summary() -> None:
    records: list[dict[str, float | None]] = []
    for i in range(10):
        hot_night = i >= 5
        records.append(
            {
                OUTCOME_SLEEP_SCORE: 74.0 if hot_night else 80.0,
                "bedroom_critical_minutes": 60.0 if hot_night else 0.0,
            }
        )

    drivers = compute_drivers(
        records,
        outcome_key=OUTCOME_SLEEP_SCORE,
        driver_keys=("bedroom_critical_minutes",),
    )

    assert drivers[0].summary == (
        "Nights with 60+ min above 20C average 6 points lower sleep score (10 nights measured)."
    )


# ---------------------------------------------------------------------------
# DB-backed service tests
# ---------------------------------------------------------------------------


async def _seed_profile(db_conn: AsyncConnection, user_id: uuid.UUID) -> None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            Profile(
                id=user_id,
                display_name="Insights Test",
                pin_hash="x" * 60,
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
            )
        )
        await session.commit()


def _activity(user_id: uuid.UUID, n: int, power: int, hr: int) -> Activity:
    return Activity(
        id=uuid.uuid4(),
        user_id=user_id,
        garmin_activity_id=1000 + n,
        activity_name="Ride",
        activity_type="cycling",
        start_utc=datetime(2026, 5, 1) + timedelta(days=n),
        avg_power_watts=power,
        avg_heart_rate_bpm=hr,
        training_load=50.0,
    )


@pytest.mark.asyncio
async def test_service_ftp_drift_reads_activities(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add_all(
            [
                _activity(user_id, 0, 200, 140),
                _activity(user_id, 2, 200, 140),
                _activity(user_id, 10, 220, 140),
                _activity(user_id, 14, 220, 140),
            ]
        )
        await session.commit()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = InsightsService(session)
        result = await service.ftp_drift(user, as_of=_day(20))
        assert result.status == "rising"
        assert result.sample_count == 4


@pytest.mark.asyncio
async def test_service_early_warning_reads_metrics_and_sleep(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        for i, (hrv, score) in enumerate([(55, 80), (53, 76), (51, 72), (49, 68)]):
            session.add(
                DailyMetric(
                    user_id=user_id,
                    calendar_date=_day(i),
                    hrv_last_night_avg_ms=hrv,
                    readiness_score=70 - i * 3,
                )
            )
            session.add(Sleep(user_id=user_id, calendar_date=_day(i), score=score))
        await session.commit()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = InsightsService(session)
        result = await service.early_warning(user, as_of=_day(3), window_days=5)
        assert result.status == "early_warning"
        assert result.fired is True


@pytest.mark.asyncio
async def test_service_drivers_builds_records_and_correlates(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        for i in range(10):
            session.add(
                Sleep(user_id=user_id, calendar_date=_day(i), score=80 - i, avg_sleep_stress=20.0)
            )
            session.add(
                DailyMetric(
                    user_id=user_id,
                    calendar_date=_day(i),
                    hrv_last_night_avg_ms=50,
                    resting_heart_rate_bpm=45,
                    stress_avg=30.0,
                )
            )
            session.add(
                WeatherDaily(
                    user_id=user_id,
                    calendar_date=_day(i),
                    source="open_meteo",
                    latitude=55.6,
                    longitude=-4.5,
                    overnight_low_c=float(i),  # rises as sleep score falls
                )
            )
        await session.commit()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = InsightsService(session)
        report = await service.drivers(user, as_of=_day(11), lookback_days=120)
        assert report.record_count == 10
        sleep_drivers = report.outcomes[OUTCOME_SLEEP_SCORE]
        assert sleep_drivers
        top = sleep_drivers[0]
        assert top.driver == "overnight_low_c"
        assert top.direction == "negative"
        assert set(DRIVER_KEYS)  # sanity: keys exist


@pytest.mark.asyncio
async def test_service_driver_records_include_bedroom_rollups(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    wake_date = date(2026, 7, 2)
    night_start_utc = datetime(2026, 7, 1, 21, 0)  # 22:00 Europe/London.
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(Sleep(user_id=user_id, calendar_date=wake_date, score=70))
        session.add(
            TemperatureReading(
                user_id=user_id,
                captured_at_utc=night_start_utc,
                temperature_c=20.2,
            )
        )
        session.add(
            TemperatureReading(
                user_id=user_id,
                captured_at_utc=night_start_utc + timedelta(minutes=15),
                temperature_c=19.7,
            )
        )
        session.add(
            FanStateReading(
                user_id=user_id,
                captured_at_utc=night_start_utc + timedelta(minutes=30),
                phase="control",
                auto_enabled=True,
                observed_temp_c=20.2,
                fan_on=True,
                fan_speed=5,
                action="apply",
            )
        )
        await session.commit()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = InsightsService(session)
        records = await service._driver_records(user, start=wake_date, end=wake_date)

    assert records == [
        {
            OUTCOME_SLEEP_SCORE: 70.0,
            "recovery_hrv_ms": None,
            "overnight_low_c": None,
            "overnight_wind_max_mph": None,
            "bedroom_warning_minutes": 30.0,
            "bedroom_critical_minutes": 15.0,
            "bedroom_fan_ran_minutes": 15.0,
            "bedroom_peak_fan_speed": 5.0,
            "prev_day_training_load": None,
            "daytime_stress_avg": None,
            "resting_heart_rate_bpm": None,
            "sleep_stress_avg": None,
        }
    ]


@pytest.mark.asyncio
async def test_service_driver_records_keep_missing_bedroom_data_none(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    wake_date = date(2026, 7, 2)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(Sleep(user_id=user_id, calendar_date=wake_date, score=70))
        await session.commit()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = InsightsService(session)
        records = await service._driver_records(user, start=wake_date, end=wake_date)

    assert records[0]["bedroom_warning_minutes"] is None
    assert records[0]["bedroom_critical_minutes"] is None
    assert records[0]["bedroom_fan_ran_minutes"] is None
    assert records[0]["bedroom_peak_fan_speed"] is None


@pytest.mark.asyncio
async def test_service_run_records_actionable_findings_idempotently(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        # Rising FTP drift evidence.
        session.add_all(
            [
                _activity(user_id, 0, 200, 140),
                _activity(user_id, 2, 200, 140),
                _activity(user_id, 10, 220, 140),
                _activity(user_id, 14, 220, 140),
            ]
        )
        # Degrading early-warning trend.
        for i, (hrv, score) in enumerate([(55, 80), (53, 76), (51, 72), (49, 68)]):
            session.add(
                DailyMetric(
                    user_id=user_id,
                    calendar_date=_day(13 + i),
                    hrv_last_night_avg_ms=hrv,
                    readiness_score=70 - i * 3,
                )
            )
            session.add(Sleep(user_id=user_id, calendar_date=_day(13 + i), score=score))
        await session.commit()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = InsightsService(session)
        result = await service.run(user, as_of=_day(16))
        assert AUDIT_TYPE_FTP_DRIFT in result["recorded"]
        assert AUDIT_TYPE_EARLY_WARNING in result["recorded"]

        audit = (
            (
                await session.execute(
                    select(Analysis).where(
                        Analysis.user_id == user_id,
                        Analysis.analysis_type.in_(
                            [AUDIT_TYPE_FTP_DRIFT, AUDIT_TYPE_EARLY_WARNING, AUDIT_TYPE_DRIVERS]
                        ),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(audit) == len(result["recorded"])

        # Idempotent: a second run on the same day records nothing new.
        again = await service.run(user, as_of=_day(16))
        assert again["recorded"] == []


# ---------------------------------------------------------------------------
# 62.2 — driver-report cache (packet round-trip + read-through)
# ---------------------------------------------------------------------------


def test_drivers_packet_round_trips() -> None:
    """`_drivers_report_from_packet` inverts `_drivers_packet` exactly."""
    report = DriversReport(
        outcomes={
            OUTCOME_SLEEP_SCORE: [
                DriverCorrelation(
                    driver="overnight_low_c",
                    outcome=OUTCOME_SLEEP_SCORE,
                    coefficient=-0.72,
                    sample_count=30,
                    summary="Warmer nights, lower sleep score.",
                ),
                DriverCorrelation(
                    driver="prev_day_training_load",
                    outcome=OUTCOME_SLEEP_SCORE,
                    coefficient=0.11,
                    sample_count=30,
                    summary=None,
                ),
            ],
            OUTCOME_RECOVERY_HRV: [],
        },
        record_count=30,
        window_start=_day(0),
        window_end=_day(30),
    )
    rebuilt = _drivers_report_from_packet(_drivers_packet(report))
    assert rebuilt == report


@pytest.mark.asyncio
async def test_record_drivers_then_cached_drivers_matches_live(
    db_conn: AsyncConnection,
) -> None:
    """The morning precompute caches a packet that `cached_drivers` reads back
    identically to a live compute."""
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        for i in range(10):
            session.add(
                Sleep(user_id=user_id, calendar_date=_day(i), score=80 - i, avg_sleep_stress=20.0)
            )
            session.add(
                DailyMetric(
                    user_id=user_id,
                    calendar_date=_day(i),
                    hrv_last_night_avg_ms=50,
                    resting_heart_rate_bpm=45,
                    stress_avg=30.0,
                )
            )
            session.add(
                WeatherDaily(
                    user_id=user_id,
                    calendar_date=_day(i),
                    source="open_meteo",
                    latitude=55.6,
                    longitude=-4.5,
                    overnight_low_c=float(i),
                )
            )
        await session.commit()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = InsightsService(session)
        live = await service.drivers(user, as_of=_day(11))

        recorded = await service.record_drivers(user, as_of=_day(11))
        assert recorded == live
        # The audit row is stored once, keyed by subject_date.
        rows = (
            (
                await session.execute(
                    select(Analysis).where(
                        Analysis.user_id == user_id,
                        Analysis.analysis_type == AUDIT_TYPE_DRIVERS,
                        Analysis.subject_date == _day(11),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1

        cached = await service.cached_drivers(user, as_of=_day(11))
        assert cached == live

        # Idempotent: recording again writes no second row.
        await service.record_drivers(user, as_of=_day(11))
        rows_again = (
            (
                await session.execute(
                    select(Analysis).where(
                        Analysis.user_id == user_id,
                        Analysis.analysis_type == AUDIT_TYPE_DRIVERS,
                        Analysis.subject_date == _day(11),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows_again) == 1


@pytest.mark.asyncio
async def test_cached_drivers_falls_back_to_live_when_no_packet(
    db_conn: AsyncConnection,
) -> None:
    """With no stored packet, `cached_drivers` returns the live compute unchanged."""
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        for i in range(10):
            session.add(
                Sleep(user_id=user_id, calendar_date=_day(i), score=80 - i, avg_sleep_stress=20.0)
            )
            session.add(
                DailyMetric(
                    user_id=user_id,
                    calendar_date=_day(i),
                    hrv_last_night_avg_ms=50,
                    resting_heart_rate_bpm=45,
                    stress_avg=30.0,
                )
            )
            session.add(
                WeatherDaily(
                    user_id=user_id,
                    calendar_date=_day(i),
                    source="open_meteo",
                    latitude=55.6,
                    longitude=-4.5,
                    overnight_low_c=float(i),
                )
            )
        await session.commit()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = InsightsService(session)
        cached = await service.cached_drivers(user, as_of=_day(11))
        live = await service.drivers(user, as_of=_day(11))
        assert cached == live
        # No packet was written by a read-through.
        row = await session.scalar(
            select(Analysis.id).where(
                Analysis.user_id == user_id,
                Analysis.analysis_type == AUDIT_TYPE_DRIVERS,
            )
        )
        assert row is None
