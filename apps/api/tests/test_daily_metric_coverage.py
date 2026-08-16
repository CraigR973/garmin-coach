from datetime import date

from src.services.daily_metric_coverage import (
    complete_body_battery_charged,
    complete_stress_avg,
    daily_aggregate_coverage,
)


def _raw(end_local: str) -> dict[str, object]:
    return {
        "stress": {
            "avgStressLevel": 28,
            "startTimestampLocal": "2026-07-31T00:00:00.0",
            "endTimestampLocal": end_local,
        },
        "body_battery": {
            "drained": 70,
            "bodyBatteryValuesArray": [[0, 16]],
            "startTimestampLocal": "2026-07-31T00:00:00.0",
            "endTimestampLocal": end_local,
        },
    }


def test_morning_snapshot_is_incomplete() -> None:
    coverage = daily_aggregate_coverage(
        date(2026, 7, 31),
        _raw("2026-07-31T08:44:00.0"),
    )

    assert coverage.status == "incomplete"
    assert coverage.stress.complete is False
    assert coverage.body_battery.complete is False


def test_next_midnight_is_complete() -> None:
    coverage = daily_aggregate_coverage(
        date(2026, 7, 31),
        _raw("2026-08-01T00:00:00.0"),
    )

    assert coverage.status == "complete"
    assert coverage.stress.complete is True
    assert coverage.body_battery.complete is True


def test_final_five_minute_sample_tolerance_is_complete() -> None:
    coverage = daily_aggregate_coverage(
        date(2025, 9, 12),
        {
            "stress": {
                "avgStressLevel": 24,
                "startTimestampLocal": "2025-09-12T00:00:00.0",
                "endTimestampLocal": "2025-09-12T23:55:00.0",
            },
            "body_battery": {
                "drained": 60,
                "bodyBatteryValuesArray": [[0, 20]],
                "startTimestampLocal": "2025-09-12T00:00:00.0",
                "endTimestampLocal": "2025-09-12T23:55:00.0",
            },
        },
    )

    assert coverage.status == "complete"


def test_missing_source_windows_are_unknown() -> None:
    coverage = daily_aggregate_coverage(date(2026, 7, 31), {})

    assert coverage.status == "unknown"
    assert coverage.stress.status == "unknown"
    assert coverage.body_battery.status == "unknown"


def test_stats_fallback_uses_wellness_window() -> None:
    coverage = daily_aggregate_coverage(
        date(2026, 7, 31),
        {
            "stats": {
                "averageStressLevel": 28,
                "bodyBatteryDrainedValue": 70,
                "bodyBatteryMostRecentValue": 16,
                "wellnessStartTimeLocal": "2026-07-31T00:00:00.0",
                "wellnessEndTimeLocal": "2026-08-01T00:00:00.0",
            }
        },
    )

    assert coverage.status == "complete"


class _MetricRow:
    calendar_date = date(2026, 7, 31)
    stress_avg = 28
    body_battery_charged = 70

    def __init__(self, raw_payload: dict[str, object]) -> None:
        self.raw_payload = raw_payload


def test_complete_value_helpers_drop_partial_aggregates() -> None:
    row = _MetricRow(_raw("2026-07-31T08:44:00.0"))

    assert complete_stress_avg(row) is None
    assert complete_body_battery_charged(row) is None


def test_complete_value_helpers_keep_closed_day_aggregates() -> None:
    row = _MetricRow(_raw("2026-08-01T00:00:00.0"))

    assert complete_stress_avg(row) == 28.0
    assert complete_body_battery_charged(row) == 70
