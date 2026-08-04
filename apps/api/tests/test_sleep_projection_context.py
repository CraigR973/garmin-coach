from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from src.models.coaching import (
    Activity,
    KnowledgeBase,
    TemperatureReading,
    WeatherDaily,
)
from src.models.profile import Profile, UserRole
from src.services.insights import (
    OUTCOME_SLEEP_SCORE,
    DriverCorrelation,
    DriversReport,
)
from src.services.nudge_alerts import build_evening_nudge_plan
from src.services.sleep_projection_context import SleepProjectionContextService


def _profile() -> Profile:
    return Profile(
        id=uuid.uuid4(),
        display_name="Projection Test",
        role=UserRole.admin,
        timezone="Europe/London",
        is_active=True,
        fan_auto_enabled=True,
    )


def _activity(
    *,
    start_utc: datetime,
    duration_sec: float,
    training_load: float,
    aerobic_training_effect: float,
) -> MagicMock:
    activity = MagicMock(spec=Activity)
    activity.activity_name = "Evening ride"
    activity.activity_type = "indoor_cycling"
    activity.start_utc = start_utc
    activity.duration_sec = duration_sec
    activity.training_load = training_load
    activity.aerobic_training_effect = aerobic_training_effect
    activity.anaerobic_training_effect = 0.5
    return activity


def _temperature(value: float, captured_at_utc: datetime) -> MagicMock:
    reading = MagicMock(spec=TemperatureReading)
    reading.temperature_c = value
    reading.captured_at_utc = captured_at_utc
    return reading


def _weather(overnight_low_c: float) -> MagicMock:
    weather = MagicMock(spec=WeatherDaily)
    weather.overnight_low_c = overnight_low_c
    weather.overnight_wind_max_mph = 7.0
    return weather


def _drivers() -> DriversReport:
    return DriversReport(
        outcomes={
            OUTCOME_SLEEP_SCORE: [
                DriverCorrelation(
                    driver="prev_day_training_load",
                    outcome=OUTCOME_SLEEP_SCORE,
                    coefficient=-0.62,
                    sample_count=14,
                    summary="Higher-load days have tracked with lower sleep scores.",
                ),
                DriverCorrelation(
                    driver="bedroom_warning_minutes",
                    outcome=OUTCOME_SLEEP_SCORE,
                    coefficient=-0.48,
                    sample_count=12,
                    summary="Warm-room minutes have tracked with lower sleep scores.",
                ),
            ]
        },
        record_count=14,
        window_start=date(2026, 6, 1),
        window_end=date(2026, 6, 20),
    )


@pytest.mark.asyncio
async def test_snapshot_projection_is_the_same_projection_used_by_the_push() -> None:
    profile = _profile()
    snapshot = SimpleNamespace(
        subject_date=date(2026, 6, 20),
        activities=[
            _activity(
                start_utc=datetime(2026, 6, 20, 17, 5),
                duration_sec=72 * 60,
                training_load=145,
                aerobic_training_effect=4.2,
            )
        ],
        sleep_protocol={},
        latest_temperature=_temperature(20.1, datetime(2026, 6, 20, 18, 50)),
        weather=_weather(15.0),
    )
    service = SleepProjectionContextService(AsyncMock())

    with patch(
        "src.services.sleep_projection_context.InsightsService.cached_drivers",
        new=AsyncMock(return_value=_drivers()),
    ):
        build = await service.build_from_snapshot(
            profile,
            snapshot,
            now_utc=datetime(2026, 6, 20, 19, 5, tzinfo=UTC),
        )

    assert build.projection.tone == "protect"
    assert any("18:05" in line for line in build.projection.evidence)
    assert any("20.1C" in line for line in build.projection.evidence)

    plan = build_evening_nudge_plan(snapshot.subject_date, build.projection)
    assert plan.title == build.projection.headline
    assert "late session" in plan.title
    assert "warm bedroom" in plan.title
    assert plan.context["prepActions"] == build.projection.prep_actions[:2]
    assert plan.context["evidence"] == build.projection.evidence


@pytest.mark.asyncio
async def test_stale_bedroom_temperature_cannot_create_a_room_risk() -> None:
    profile = _profile()
    snapshot = SimpleNamespace(
        subject_date=date(2026, 6, 20),
        activities=[
            _activity(
                start_utc=datetime(2026, 6, 20, 8, 0),
                duration_sec=35 * 60,
                training_load=28,
                aerobic_training_effect=1.6,
            )
        ],
        sleep_protocol={},
        latest_temperature=_temperature(20.1, datetime(2026, 6, 20, 17, 0)),
        weather=_weather(9.0),
    )
    service = SleepProjectionContextService(AsyncMock())

    with patch(
        "src.services.sleep_projection_context.InsightsService.cached_drivers",
        new=AsyncMock(return_value=_drivers()),
    ):
        build = await service.build_from_snapshot(
            profile,
            snapshot,
            now_utc=datetime(2026, 6, 20, 19, 5, tzinfo=UTC),
        )

    assert build.projection.tone == "routine"
    assert not any("20.1C" in line for line in build.projection.evidence)


@pytest.mark.asyncio
async def test_scheduler_build_loads_the_focused_projection_sources(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        profile = _profile()
        subject_date = date(2026, 6, 20)
        session.add(profile)
        await session.flush()
        session.add_all(
            [
                Activity(
                    user_id=profile.id,
                    garmin_activity_id=184001,
                    activity_name="Evening ride",
                    activity_type="indoor_cycling",
                    start_utc=datetime(2026, 6, 20, 17, 5),
                    duration_sec=72 * 60,
                    training_load=145,
                    aerobic_training_effect=4.2,
                    anaerobic_training_effect=0.5,
                    exclude_from_recovery=False,
                    raw_summary={},
                ),
                KnowledgeBase(
                    user_id=profile.id,
                    section="sleep_protocol",
                    version=1,
                    is_active=True,
                    content={"preCoolTemperatureC": 16.5},
                ),
                TemperatureReading(
                    user_id=profile.id,
                    source="hive",
                    captured_at_utc=datetime(2026, 6, 20, 18, 50),
                    temperature_c=20.1,
                    raw_payload={},
                ),
                WeatherDaily(
                    user_id=profile.id,
                    calendar_date=subject_date,
                    source="open_meteo",
                    latitude=55.6045,
                    longitude=-4.5249,
                    overnight_low_c=15.0,
                    overnight_wind_max_mph=7.0,
                ),
            ]
        )
        await session.flush()

        with patch(
            "src.services.sleep_projection_context.InsightsService.cached_drivers",
            new=AsyncMock(return_value=_drivers()),
        ):
            build = await SleepProjectionContextService(session).build(
                profile,
                subject_date=subject_date,
                now_utc=datetime(2026, 6, 20, 19, 5, tzinfo=UTC),
            )

        assert build.projection.tone == "protect"
        assert "late session" in build.projection.headline
        assert build.projection.protocol["preCoolTemperatureC"] == 16.5
