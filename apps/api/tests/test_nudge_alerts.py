from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock

from src.models.coaching import TemperatureReading
from src.services.nudge_alerts import (
    FreshnessSnapshot,
    build_evening_nudge_plan,
    evaluate_stale_sources,
    evaluate_thermal_alert,
    is_evening_nudge_due,
)


def _temperature(value: float, captured_at: datetime) -> MagicMock:
    reading = MagicMock(spec=TemperatureReading)
    reading.id = uuid.uuid4()
    reading.user_id = uuid.uuid4()
    reading.temperature_c = value
    reading.captured_at_utc = captured_at
    return reading


def test_evening_nudge_due_uses_profile_timezone() -> None:
    assert (
        is_evening_nudge_due(
            timezone_name="Europe/London",
            now_utc=datetime(2026, 6, 20, 19, 5, tzinfo=UTC),
        )
        is True
    )
    assert (
        is_evening_nudge_due(
            timezone_name="Europe/London",
            now_utc=datetime(2026, 6, 20, 19, 30, tzinfo=UTC),
        )
        is False
    )


def test_evening_nudge_copy_contains_sleep_protocol_steps() -> None:
    plan = build_evening_nudge_plan(date(2026, 6, 20))
    assert plan.tag == "sleep-protocol-2026-06-20"
    assert "20:00 breathing" in plan.body
    assert "17C" in plan.body
    assert "21:30" in plan.body
    assert "22:00" in plan.body
    assert "23:15" in plan.body


def test_thermal_precool_alert_before_seal_window() -> None:
    plan = evaluate_thermal_alert(
        _temperature(18.2, datetime(2026, 6, 20, 18, 10)),
        timezone_name="Europe/London",
        now_utc=datetime(2026, 6, 20, 18, 15, tzinfo=UTC),
    )
    assert plan is not None
    assert plan.context["rule"] == "pre_cool_17c"
    assert "pre-cooling" in plan.body


def test_thermal_seal_alert_near_2200() -> None:
    plan = evaluate_thermal_alert(
        _temperature(18.1, datetime(2026, 6, 20, 20, 55)),
        timezone_name="Europe/London",
        now_utc=datetime(2026, 6, 20, 20, 58, tzinfo=UTC),
    )
    assert plan is not None
    assert plan.context["rule"] == "seal_22"
    assert "Seal" in plan.title


def test_thermal_peak_alert_uses_disruption_threshold() -> None:
    plan = evaluate_thermal_alert(
        _temperature(19.7, datetime(2026, 6, 20, 20, 0)),
        timezone_name="Europe/London",
        now_utc=datetime(2026, 6, 20, 20, 5, tzinfo=UTC),
    )
    assert plan is not None
    assert plan.context["rule"] == "peak_19_5c"
    assert plan.severity == "warning"
    assert "19.5C" in plan.body


def test_thermal_critical_alert_over_20c() -> None:
    plan = evaluate_thermal_alert(
        _temperature(20.2, datetime(2026, 6, 20, 20, 0)),
        timezone_name="Europe/London",
        now_utc=datetime(2026, 6, 20, 20, 5, tzinfo=UTC),
    )
    assert plan is not None
    assert plan.context["rule"] == "peak_20c"
    assert plan.severity == "critical"


def test_stale_source_alerts_distinguish_sources() -> None:
    snapshot = FreshnessSnapshot(
        local_date=date(2026, 6, 20),
        local_now=datetime(2026, 6, 20, 20, 0),
        now_utc=datetime(2026, 6, 20, 19, 0),
        last_garmin_recorded_at_utc=datetime(2026, 6, 19, 6, 45),
        last_hive_captured_at_utc=datetime(2026, 6, 20, 18, 0),
        latest_weather_date=date(2026, 6, 19),
    )

    alerts = evaluate_stale_sources(snapshot)

    assert {alert.context["source"] for alert in alerts} == {"garmin", "hive", "weather"}
    assert {alert.title for alert in alerts} == {
        "Garmin data missing",
        "Hive temperature stale",
        "Weather data missing",
    }


def test_fresh_sources_do_not_alert() -> None:
    snapshot = FreshnessSnapshot(
        local_date=date(2026, 6, 20),
        local_now=datetime(2026, 6, 20, 20, 0),
        now_utc=datetime(2026, 6, 20, 19, 0),
        last_garmin_recorded_at_utc=datetime(2026, 6, 20, 6, 45),
        last_hive_captured_at_utc=datetime(2026, 6, 20, 18, 30),
        latest_weather_date=date(2026, 6, 20),
    )

    assert evaluate_stale_sources(snapshot) == []


def test_stale_hive_threshold_is_45_minutes() -> None:
    snapshot = FreshnessSnapshot(
        local_date=date(2026, 6, 20),
        local_now=datetime(2026, 6, 20, 20, 0),
        now_utc=datetime(2026, 6, 20, 19, 0),
        last_garmin_recorded_at_utc=datetime(2026, 6, 20, 6, 45),
        last_hive_captured_at_utc=datetime(2026, 6, 20, 18, 14, 59),
        latest_weather_date=date(2026, 6, 20),
    )

    alerts = evaluate_stale_sources(snapshot)

    assert [alert.context["source"] for alert in alerts] == ["hive"]


def test_recent_hive_threshold_boundary_is_fresh() -> None:
    snapshot = FreshnessSnapshot(
        local_date=date(2026, 6, 20),
        local_now=datetime(2026, 6, 20, 20, 0),
        now_utc=datetime(2026, 6, 20, 19, 0),
        last_garmin_recorded_at_utc=datetime(2026, 6, 20, 6, 45),
        last_hive_captured_at_utc=datetime(2026, 6, 20, 19, 0) - timedelta(minutes=45),
        latest_weather_date=date(2026, 6, 20),
    )

    assert evaluate_stale_sources(snapshot) == []
