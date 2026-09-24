import dataclasses
import json
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import pytest

from src.services.daily_metric_coverage import (
    COVERAGE_FACTS,
    CoverageSource,
    DayAggregates,
    complete_body_battery_charged,
    complete_stress_avg,
    daily_aggregate_coverage,
    morning_body_battery_charged,
)
from src.services.garmin_sync import GarminDailyPayloads, parse_daily_metric_fields

FIXTURES = Path(__file__).parent / "fixtures" / "garmin"


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


def _coverage(calendar_date: date, raw_payload: Mapping[str, Any]) -> Any:
    return daily_aggregate_coverage(calendar_date, CoverageSource.from_document(raw_payload))


def test_morning_snapshot_is_incomplete() -> None:
    coverage = _coverage(date(2026, 7, 31), _raw("2026-07-31T08:44:00.0"))

    assert coverage.status == "incomplete"
    assert coverage.stress.complete is False
    assert coverage.body_battery.complete is False


def test_next_midnight_is_complete() -> None:
    coverage = _coverage(date(2026, 7, 31), _raw("2026-08-01T00:00:00.0"))

    assert coverage.status == "complete"
    assert coverage.stress.complete is True
    assert coverage.body_battery.complete is True


def test_final_five_minute_sample_tolerance_is_complete() -> None:
    coverage = _coverage(
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
    coverage = _coverage(date(2026, 7, 31), {})

    assert coverage.status == "unknown"
    assert coverage.stress.status == "unknown"
    assert coverage.body_battery.status == "unknown"


def test_stats_fallback_uses_wellness_window() -> None:
    coverage = _coverage(
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


def _day(raw_payload: Mapping[str, Any]) -> DayAggregates:
    return DayAggregates(
        calendar_date=date(2026, 7, 31),
        phase="settled",
        stress_avg=28,
        body_battery_charged=70,
        body_battery_drained=None,
        body_battery_end=None,
        source=CoverageSource.from_document(raw_payload),
    )


def test_complete_value_helpers_drop_partial_aggregates() -> None:
    day = _day(_raw("2026-07-31T08:44:00.0"))

    assert complete_stress_avg(day) is None
    assert complete_body_battery_charged(day) is None


def test_complete_value_helpers_keep_closed_day_aggregates() -> None:
    day = _day(_raw("2026-08-01T00:00:00.0"))

    assert complete_stress_avg(day) == 28.0
    assert complete_body_battery_charged(day) == 70


def test_morning_charge_keeps_only_a_real_partial_window() -> None:
    partial = _day(_raw("2026-07-31T08:44:00.0"))
    complete = _day(_raw("2026-08-01T00:00:00.0"))
    unknown = _day({})

    assert morning_body_battery_charged(partial) == 70
    assert morning_body_battery_charged(complete) is None
    assert morning_body_battery_charged(unknown) is None


# --------------------------------------------------------------------------
# Batch 280: the contract is ten facts, never the document
# --------------------------------------------------------------------------


def test_coverage_refuses_a_whole_document() -> None:
    """280.3: a caller cannot hand the coverage function a document by accident."""
    with pytest.raises(TypeError, match="CoverageSource"):
        daily_aggregate_coverage(date(2026, 7, 31), _raw("2026-08-01T00:00:00.0"))  # type: ignore[arg-type]


def test_the_facts_are_nine_keys_and_one_boolean() -> None:
    """The whole input to a decision, listed once and matching the dataclass exactly."""
    fields = [fact.field for fact in COVERAGE_FACTS]
    assert fields == [field.name for field in dataclasses.fields(CoverageSource)]
    keys = {(fact.section, fact.key) for fact in COVERAGE_FACTS}
    assert len(keys) == 10
    truthy = [fact for fact in COVERAGE_FACTS if fact.kind == "truthy"]
    assert [(fact.section, fact.key) for fact in truthy] == [
        ("body_battery", "bodyBatteryValuesArray")
    ]
    assert {fact.section for fact in COVERAGE_FACTS} == {"stress", "stats", "body_battery"}


def test_the_values_array_arrives_as_a_boolean_and_still_picks_the_source() -> None:
    """280.3: the truthiness test survives without a stub array standing in for it.

    A Body Battery response reporting only its values array is still the source
    the typed columns were promoted from, so its window — not the stats window —
    decides coverage. Nothing in the source holds an array, real or invented.
    """
    document = {
        "body_battery": {
            "bodyBatteryValuesArray": [[1785452400000, 12]],
            "startTimestampLocal": "2026-07-31T00:00:00.0",
            "endTimestampLocal": "2026-07-31T08:44:00.0",
        },
        "stats": {
            "wellnessStartTimeLocal": "2026-07-31T00:00:00.0",
            "wellnessEndTimeLocal": "2026-08-01T00:00:00.0",
        },
    }
    source = CoverageSource.from_document(document)

    assert source.battery_values_reported is True
    assert all(
        value is None or isinstance(value, bool | str)
        for value in dataclasses.asdict(source).values()
    )
    assert daily_aggregate_coverage(date(2026, 7, 31), source).body_battery.status == "incomplete"

    emptied = CoverageSource.from_document(
        {**document, "body_battery": {**document["body_battery"], "bodyBatteryValuesArray": []}}
    )
    assert emptied.battery_values_reported is False
    # With nothing reported the stats window decides, exactly as before.
    assert daily_aggregate_coverage(date(2026, 7, 31), emptied).body_battery.status == "complete"


@pytest.mark.parametrize(
    "value",
    [[], [[0, 1]], {}, {"a": 1}, "", "x", 0, 1, 0.0, 2.5, True, False, None],
    ids=repr,
)
def test_each_fact_kind_reads_a_value_the_way_python_always_did(value: Any) -> None:
    """``truthy`` is ``bool()``, ``reported`` is ``is not None``, ``text`` keeps strings."""
    source = CoverageSource.from_document(
        {
            "body_battery": {"bodyBatteryValuesArray": value, "charged": value},
            "stress": {"startTimestampLocal": value},
        }
    )
    assert source.battery_values_reported is bool(value)
    assert source.battery_charged_reported is (value is not None)
    assert source.stress_start_local == (value if isinstance(value, str) else None)


@pytest.mark.parametrize("root", [None, [], ["stress"], "stress", 7])
def test_a_document_that_is_not_an_object_reads_as_empty(root: Any) -> None:
    assert CoverageSource.from_document(root) == CoverageSource.from_document({})


# --------------------------------------------------------------------------
# Batch 280: the new reading agrees with the old whole-document one
# --------------------------------------------------------------------------


def _pre_280_coverage(calendar_date: date, raw_payload: Any) -> tuple[str, str]:
    """The whole-document algorithm as it stood before Batch 280, frozen as the oracle."""

    def mapping(value: Any) -> Mapping[str, Any]:
        return value if isinstance(value, Mapping) else {}

    def parse(value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value.replace(tzinfo=None)
        if not isinstance(value, str) or not value:
            return None
        try:
            return datetime.fromisoformat(value.replace(" ", "T")).replace(tzinfo=None)
        except ValueError:
            return None

    def status(payload: Mapping[str, Any], start_key: str, end_key: str) -> str:
        start, end = parse(payload.get(start_key)), parse(payload.get(end_key))
        if start is None or end is None:
            return "unknown"
        day_start = datetime.combine(calendar_date, time.min)
        complete_after = day_start + timedelta(days=1) - timedelta(minutes=5)
        return "complete" if start <= day_start and end >= complete_after else "incomplete"

    raw = mapping(raw_payload)
    stress, stats, battery = (mapping(raw.get(k)) for k in ("stress", "stats", "body_battery"))
    stress_status = (
        status(stress, "startTimestampLocal", "endTimestampLocal")
        if stress.get("avgStressLevel") is not None
        else status(stats, "wellnessStartTimeLocal", "wellnessEndTimeLocal")
    )
    has_battery = (
        battery.get("charged") is not None
        or battery.get("drained") is not None
        or bool(battery.get("bodyBatteryValuesArray"))
    )
    battery_status = (
        status(battery, "startTimestampLocal", "endTimestampLocal")
        if has_battery
        else status(stats, "wellnessStartTimeLocal", "wellnessEndTimeLocal")
    )
    return stress_status, battery_status


def _fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


def _stored_documents() -> list[tuple[date, Any]]:
    """Documents built by the real write path from real Garmin responses.

    Every stored production row has this one shape — all three sections objects,
    the ten keys present with their usual types (measured 2026-09-23, 550 rows) —
    in a partial morning window and a closed day. The rest are the shapes the
    Python reader has always tolerated.
    """
    day = date(2026, 7, 31)
    complete = parse_daily_metric_fields(
        day,
        GarminDailyPayloads(
            stress=_fixture("stress_2026-07-31_complete.json"),
            body_battery=_fixture("body_battery_2026-07-31_complete.json"),
        ),
    )["raw_payload"]
    partial = parse_daily_metric_fields(
        day,
        GarminDailyPayloads(
            stress={
                "calendarDate": "2026-07-31",
                "startTimestampLocal": "2026-07-31T00:00:00.0",
                "endTimestampLocal": "2026-07-31T08:44:00.0",
                "avgStressLevel": 12,
            },
            body_battery=[
                {
                    "date": "2026-07-31",
                    "charged": 81,
                    "drained": 1,
                    "startTimestampLocal": "2026-07-31T00:00:00.0",
                    "endTimestampLocal": "2026-07-31T08:44:00.0",
                    "bodyBatteryValuesArray": [[1785452400000, 12]],
                }
            ],
        ),
    )["raw_payload"]
    return [
        (day, complete),
        (day, partial),
        (day, _raw("2026-08-01T00:00:00.0")),
        (day, _raw("2026-07-31T08:44:00.0")),
        (day, {}),
        (day, {"stress": [], "body_battery": "x", "stats": None}),
        (day, {"body_battery": {"bodyBatteryValuesArray": []}}),
        (day, [1, 2]),
    ]


def test_the_ten_facts_decide_exactly_what_the_whole_document_decided() -> None:
    """280.5: coverage from the facts equals coverage from the document it came from."""
    for calendar_date, document in _stored_documents():
        coverage = daily_aggregate_coverage(calendar_date, CoverageSource.from_document(document))
        assert (coverage.stress.status, coverage.body_battery.status) == _pre_280_coverage(
            calendar_date, document
        ), document


def test_the_real_fixtures_cover_both_outcomes() -> None:
    """The oracle comparison above is not vacuous: it sees complete and partial days."""
    statuses = {
        daily_aggregate_coverage(day, CoverageSource.from_document(doc)).status
        for day, doc in _stored_documents()[:2]
    }
    assert statuses == {"complete", "incomplete"}
