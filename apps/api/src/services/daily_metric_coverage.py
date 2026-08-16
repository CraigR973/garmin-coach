"""Coverage checks for Garmin's local-day stress and Body Battery aggregates.

Garmin exposes these figures over a local-midnight-to-now window.  A row written
in the morning therefore contains valid *partial* values, but they are not a
finished day's totals.  The raw payload already carries the source window, so
consumers can fail closed without a schema column or a guessed clock cutoff.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Literal

CoverageStatus = Literal["complete", "incomplete", "unknown"]

# Garmin's historical series contains a genuine closed day ending at 23:55.
# Treat one final five-minute sample interval as complete; morning snapshots are
# hours short and remain unambiguously incomplete.
FINAL_SAMPLE_TOLERANCE = timedelta(minutes=5)


@dataclass(frozen=True)
class SourceCoverage:
    status: CoverageStatus
    start_local: datetime | None
    end_local: datetime | None

    @property
    def complete(self) -> bool:
        return self.status == "complete"


@dataclass(frozen=True)
class DailyAggregateCoverage:
    stress: SourceCoverage
    body_battery: SourceCoverage

    @property
    def status(self) -> CoverageStatus:
        statuses = {self.stress.status, self.body_battery.status}
        if statuses == {"complete"}:
            return "complete"
        if "incomplete" in statuses:
            return "incomplete"
        return "unknown"

    @property
    def as_of_local(self) -> datetime | None:
        ends = [
            end for end in (self.stress.end_local, self.body_battery.end_local) if end is not None
        ]
        return min(ends) if ends else None


def daily_aggregate_coverage(
    calendar_date: date,
    raw_payload: Mapping[str, Any] | None,
) -> DailyAggregateCoverage:
    """Resolve whether stored stress and Body Battery cover ``calendar_date``.

    The parser prefers the dedicated stress / Body Battery responses and falls
    back to Garmin's daily stats response.  Coverage follows the same source
    preference so the flag describes the values that were actually promoted to
    the typed columns.
    """
    raw = _mapping(raw_payload)
    stress = _mapping(raw.get("stress"))
    stats = _mapping(raw.get("stats"))
    body_battery = _mapping(raw.get("body_battery"))

    stress_source = (
        (stress, "startTimestampLocal", "endTimestampLocal")
        if stress.get("avgStressLevel") is not None
        else (stats, "wellnessStartTimeLocal", "wellnessEndTimeLocal")
    )
    has_body_battery = (
        body_battery.get("charged") is not None
        or body_battery.get("drained") is not None
        or bool(body_battery.get("bodyBatteryValuesArray"))
    )
    battery_source = (
        (body_battery, "startTimestampLocal", "endTimestampLocal")
        if has_body_battery
        else (stats, "wellnessStartTimeLocal", "wellnessEndTimeLocal")
    )

    return DailyAggregateCoverage(
        stress=_source_coverage(calendar_date, *stress_source),
        body_battery=_source_coverage(calendar_date, *battery_source),
    )


def coverage_packet(coverage: DailyAggregateCoverage) -> dict[str, str | None]:
    """Small JSON-safe packet explaining why aggregate values are present/absent."""
    return {
        "status": coverage.status,
        "stressStatus": coverage.stress.status,
        "bodyBatteryStatus": coverage.body_battery.status,
        "asOfLocal": (
            coverage.as_of_local.isoformat() if coverage.as_of_local is not None else None
        ),
    }


def complete_stress_avg(row: Any) -> float | None:
    """Return stress only when the stored row covers the complete local day."""
    coverage = daily_aggregate_coverage(row.calendar_date, row.raw_payload)
    value = getattr(row, "stress_avg", None)
    return float(value) if value is not None and coverage.stress.complete else None


def complete_body_battery_charged(row: Any) -> int | None:
    """Return Body Battery charge only for complete local-day aggregates."""
    coverage = daily_aggregate_coverage(row.calendar_date, row.raw_payload)
    value = getattr(row, "body_battery_charged", None)
    return int(value) if value is not None and coverage.body_battery.complete else None


def complete_body_battery_drained(row: Any) -> int | None:
    """Return Body Battery drain only for complete local-day aggregates."""
    coverage = daily_aggregate_coverage(row.calendar_date, row.raw_payload)
    value = getattr(row, "body_battery_drained", None)
    return int(value) if value is not None and coverage.body_battery.complete else None


def complete_body_battery_end(row: Any) -> int | None:
    """Return Body Battery end only for complete local-day aggregates."""
    coverage = daily_aggregate_coverage(row.calendar_date, row.raw_payload)
    value = getattr(row, "body_battery_end", None)
    return int(value) if value is not None and coverage.body_battery.complete else None


def _source_coverage(
    calendar_date: date,
    payload: Mapping[str, Any],
    start_key: str,
    end_key: str,
) -> SourceCoverage:
    start_local = _parse_local_datetime(payload.get(start_key))
    end_local = _parse_local_datetime(payload.get(end_key))
    if start_local is None or end_local is None:
        return SourceCoverage("unknown", start_local, end_local)

    day_start = datetime.combine(calendar_date, time.min)
    complete_after = day_start + timedelta(days=1) - FINAL_SAMPLE_TOLERANCE
    status: CoverageStatus = (
        "complete" if start_local <= day_start and end_local >= complete_after else "incomplete"
    )
    return SourceCoverage(status, start_local, end_local)


def _parse_local_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace(" ", "T")
    try:
        return datetime.fromisoformat(normalized).replace(tzinfo=None)
    except ValueError:
        return None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}
