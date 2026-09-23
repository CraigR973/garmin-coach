"""Coverage checks for Garmin's local-day stress and Body Battery aggregates.

Garmin exposes these figures over a local-midnight-to-now window.  A row written
in the morning therefore contains valid *partial* values, but they are not a
finished day's totals.  The raw payload already carries the source window, so
consumers can fail closed without a schema column or a guessed clock cutoff.

**Coverage is decided from ten facts, never from the document (Batch 280).** A
decision reads nine keys across three sections of Garmin's stored daily document
plus one truthiness test, and nothing else. Reading them used to mean loading
the whole document — about 40 KB uncompressed per row — so every history window
that gated a stress or Body Battery figure shipped that document across the wire
once per row: 26 GB over the 92 days ``pg_stat_statements`` covered on
2026-09-23. :data:`COVERAGE_FACTS` lists the ten facts once;
``bulk_history_reads.select_day_aggregates`` projects them server-side from that
list, and :meth:`CoverageSource.from_document` reads them out of a document a
caller already holds in memory.

:func:`daily_aggregate_coverage` accepts only a :class:`CoverageSource`, so a
caller cannot hand it a whole document by accident. The Body Battery values
array arrives as a boolean — whether it held anything — because that is all the
decision ever asked of it; nothing is fabricated to stand in for the array.
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

#: How a fact is read from the value stored under its key. ``reported`` is
#: ``value is not None``; ``text`` keeps a string and nothing else; ``truthy`` is
#: Python's ``bool(value)``. The SQL projection implements the same three.
FactKind = Literal["reported", "text", "truthy"]


@dataclass(frozen=True)
class CoverageFact:
    """One input to a coverage decision: where it lives and how it is read."""

    field: str
    section: str
    key: str
    kind: FactKind


#: Everything a coverage decision reads (Batch 280): nine keys and one
#: truthiness test. ``field`` is both the :class:`CoverageSource` attribute and
#: the label the server-side projection gives the value.
COVERAGE_FACTS: tuple[CoverageFact, ...] = (
    CoverageFact("stress_reported", "stress", "avgStressLevel", "reported"),
    CoverageFact("stress_start_local", "stress", "startTimestampLocal", "text"),
    CoverageFact("stress_end_local", "stress", "endTimestampLocal", "text"),
    CoverageFact("stats_start_local", "stats", "wellnessStartTimeLocal", "text"),
    CoverageFact("stats_end_local", "stats", "wellnessEndTimeLocal", "text"),
    CoverageFact("battery_charged_reported", "body_battery", "charged", "reported"),
    CoverageFact("battery_drained_reported", "body_battery", "drained", "reported"),
    CoverageFact("battery_values_reported", "body_battery", "bodyBatteryValuesArray", "truthy"),
    CoverageFact("battery_start_local", "body_battery", "startTimestampLocal", "text"),
    CoverageFact("battery_end_local", "body_battery", "endTimestampLocal", "text"),
)


@dataclass(frozen=True)
class CoverageSource:
    """The ten facts one coverage decision is made from, and nothing else."""

    stress_reported: bool
    stress_start_local: str | None
    stress_end_local: str | None
    stats_start_local: str | None
    stats_end_local: str | None
    battery_charged_reported: bool
    battery_drained_reported: bool
    battery_values_reported: bool
    battery_start_local: str | None
    battery_end_local: str | None

    @classmethod
    def from_document(cls, raw_payload: Mapping[str, Any] | None) -> CoverageSource:
        """Read the facts out of a document that is already in memory.

        For the write path, which holds Garmin's response before storing it,
        and for a reader that loads one row whole for another reason. Never load
        a row whole in order to call this — project the facts with
        ``bulk_history_reads.select_day_aggregates`` instead.
        """
        raw = _mapping(raw_payload)
        values: dict[str, Any] = {
            fact.field: _read_fact(_mapping(raw.get(fact.section)).get(fact.key), fact.kind)
            for fact in COVERAGE_FACTS
        }
        return cls(**values)

    @classmethod
    def from_row(cls, row: Any) -> CoverageSource:
        """Read the facts off a projected row labelled with the field names."""
        values: dict[str, Any] = {fact.field: getattr(row, fact.field) for fact in COVERAGE_FACTS}
        return cls(**values)


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
    source: CoverageSource,
) -> DailyAggregateCoverage:
    """Resolve whether stored stress and Body Battery cover ``calendar_date``.

    The parser prefers the dedicated stress / Body Battery responses and falls
    back to Garmin's daily stats response.  Coverage follows the same source
    preference so the flag describes the values that were actually promoted to
    the typed columns.
    """
    if not isinstance(source, CoverageSource):
        raise TypeError(
            "daily_aggregate_coverage takes a CoverageSource, not a document: project "
            "the facts with bulk_history_reads.select_day_aggregates, or convert a "
            "document already in memory with CoverageSource.from_document"
        )
    stress_window = (
        (source.stress_start_local, source.stress_end_local)
        if source.stress_reported
        else (source.stats_start_local, source.stats_end_local)
    )
    has_body_battery = (
        source.battery_charged_reported
        or source.battery_drained_reported
        or source.battery_values_reported
    )
    battery_window = (
        (source.battery_start_local, source.battery_end_local)
        if has_body_battery
        else (source.stats_start_local, source.stats_end_local)
    )

    return DailyAggregateCoverage(
        stress=_source_coverage(calendar_date, *stress_window),
        body_battery=_source_coverage(calendar_date, *battery_window),
    )


@dataclass(frozen=True)
class DayAggregates:
    """One observation's running local-day totals, and the window they cover.

    What every "is this a finished day's figure?" reader needs from a
    ``daily_metrics`` row: the four aggregate columns, which phase observed them,
    and the coverage facts. A projected read of these is a couple of hundred
    bytes; the document the facts live in is about forty thousand.
    """

    calendar_date: date
    phase: str
    stress_avg: float | None
    body_battery_charged: int | None
    body_battery_drained: int | None
    body_battery_end: int | None
    source: CoverageSource

    @property
    def coverage(self) -> DailyAggregateCoverage:
        return daily_aggregate_coverage(self.calendar_date, self.source)

    @classmethod
    def from_row(cls, row: Any) -> DayAggregates:
        """From a row produced by ``bulk_history_reads.select_day_aggregates``."""
        return cls(
            calendar_date=row.calendar_date,
            phase=row.phase,
            stress_avg=row.stress_avg,
            body_battery_charged=row.body_battery_charged,
            body_battery_drained=row.body_battery_drained,
            body_battery_end=row.body_battery_end,
            source=CoverageSource.from_row(row),
        )

    @classmethod
    def from_metric(cls, metric: Any) -> DayAggregates:
        """From a ``DailyMetric`` already loaded whole for another reason.

        The morning read loads the wake row whole because it also reads fitness
        age and the training fields out of the document. A history window has no
        such reason and uses the projection.
        """
        return cls(
            calendar_date=metric.calendar_date,
            phase=metric.phase,
            stress_avg=metric.stress_avg,
            body_battery_charged=metric.body_battery_charged,
            body_battery_drained=metric.body_battery_drained,
            body_battery_end=metric.body_battery_end,
            source=CoverageSource.from_document(metric.raw_payload),
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


def complete_stress_avg(day: DayAggregates) -> float | None:
    """Return stress only when the stored row covers the complete local day."""
    value = day.stress_avg
    return float(value) if value is not None and day.coverage.stress.complete else None


def complete_body_battery_charged(day: DayAggregates) -> int | None:
    """Return Body Battery charge only for complete local-day aggregates."""
    value = day.body_battery_charged
    return int(value) if value is not None and day.coverage.body_battery.complete else None


def morning_body_battery_charged(day: DayAggregates) -> int | None:
    """Return charge only for a genuine partial local-day morning window.

    Garmin's charge at the wake sync is the overnight recharge accumulated
    since local midnight.  It is useful before the day closes, unlike drain,
    but an unknown or already-complete source window cannot prove that meaning
    and therefore fails closed.
    """
    value = day.body_battery_charged
    return (
        int(value)
        if value is not None and day.coverage.body_battery.status == "incomplete"
        else None
    )


def complete_body_battery_drained(day: DayAggregates) -> int | None:
    """Return Body Battery drain only for complete local-day aggregates."""
    value = day.body_battery_drained
    return int(value) if value is not None and day.coverage.body_battery.complete else None


def complete_body_battery_end(day: DayAggregates) -> int | None:
    """Return Body Battery end only for complete local-day aggregates."""
    value = day.body_battery_end
    return int(value) if value is not None and day.coverage.body_battery.complete else None


def _source_coverage(
    calendar_date: date,
    start_value: str | None,
    end_value: str | None,
) -> SourceCoverage:
    start_local = _parse_local_datetime(start_value)
    end_local = _parse_local_datetime(end_value)
    if start_local is None or end_local is None:
        return SourceCoverage("unknown", start_local, end_local)

    day_start = datetime.combine(calendar_date, time.min)
    complete_after = day_start + timedelta(days=1) - FINAL_SAMPLE_TOLERANCE
    status: CoverageStatus = (
        "complete" if start_local <= day_start and end_local >= complete_after else "incomplete"
    )
    return SourceCoverage(status, start_local, end_local)


def _parse_local_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace(" ", "T")
    try:
        return datetime.fromisoformat(normalized).replace(tzinfo=None)
    except ValueError:
        return None


def _read_fact(value: Any, kind: FactKind) -> bool | str | None:
    if kind == "reported":
        return value is not None
    if kind == "text":
        return value if isinstance(value, str) else None
    return bool(value)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}
