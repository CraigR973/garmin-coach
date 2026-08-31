"""The history windows stop shipping the raw provider payload (2026-08-30 egress incident).

Two things are pinned here, and they fail for different reasons:

* **The wire.** Every audited hot path is driven through a recording session
  that captures the real ``select()`` it issues, and the compiled SQL is
  asserted not to name ``sleep.raw_payload`` / ``temperature_readings
  .raw_payload``. A new call site added without the loader option fails here
  rather than in a Supabase egress bill — which is how the 2026-08-30 incident
  was found, five weeks after the reads that caused it shipped.
* **The arithmetic.** The same recording session feeds real rows back, so the
  rollups, peaks and correlations are computed end to end and compared against
  the values the un-projected query produced. Narrowing a query must not move a
  number.

``daily_metrics.raw_payload`` is deliberately *not* covered: it is still read
(``daily_metric_coverage``), so a test asserting its absence would be asserting
a bug. The floor below states that explicitly so a later sweep cannot quietly
widen itself into that column.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Select
from sqlalchemy.dialects import postgresql

from src.models.coaching import DailyMetric, FanStateReading, Sleep, TemperatureReading
from src.models.profile import Profile, UserRole
from src.services.bulk_history_reads import (
    fan_series_columns,
    temperature_series_columns,
    without_sleep_raw_payload,
)

# --------------------------------------------------------------------------
# A session that records statements instead of executing them
# --------------------------------------------------------------------------


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[Any]:
        return list(self._rows)

    def first(self) -> Any | None:
        return self._rows[0] if self._rows else None

    def unique(self) -> _Result:
        return self


class RecordingSession:
    """Captures every statement and replays canned rows keyed by entity."""

    def __init__(self, rows_by_entity: dict[type, list[Any]] | None = None) -> None:
        self.statements: list[Select[Any]] = []
        self._rows = rows_by_entity or {}

    async def execute(self, statement: Any, *args: Any, **kwargs: Any) -> _Result:
        self.statements.append(statement)
        return _Result(self._rows.get(_entity_of(statement), []))

    async def scalar(self, statement: Any, *args: Any, **kwargs: Any) -> Any | None:
        self.statements.append(statement)
        rows = self._rows.get(_entity_of(statement), [])
        return rows[0] if rows else None

    async def flush(self) -> None:  # pragma: no cover - services may call it
        return None

    def add(self, _obj: Any) -> None:  # pragma: no cover - services may call it
        return None


def _entity_of(statement: Any) -> type | None:
    try:
        descriptions = statement.column_descriptions
    except AttributeError:  # pragma: no cover - non-ORM statement
        return None
    for description in descriptions:
        entity = description.get("entity")
        if entity is not None:
            return entity  # type: ignore[no-any-return]
    return None


def compiled(statement: Any) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


def sql_for(session: RecordingSession, entity: type) -> list[str]:
    return [compiled(s) for s in session.statements if _entity_of(s) is entity]


def _profile() -> Profile:
    return Profile(
        id=uuid.uuid4(),
        display_name="Mark",
        timezone="Europe/London",
        role=UserRole.admin,
    )


# --------------------------------------------------------------------------
# The loader options themselves
# --------------------------------------------------------------------------


def test_sleep_option_drops_only_the_raw_payload() -> None:
    from sqlalchemy import select

    sql = compiled(select(Sleep).options(without_sleep_raw_payload()))
    assert "raw_payload" not in sql
    # The typed reads every correlation depends on must survive.
    for column in (
        "sleep.score",
        "sleep.rem_sleep_sec",
        "sleep.awake_sleep_sec",
        "sleep.avg_sleep_stress",
        "sleep.age_adjusted_score",
        "sleep.duration_sec",
        "sleep.factors_json",
    ):
        assert column in sql, column


def test_temperature_option_selects_exactly_the_series_columns() -> None:
    from sqlalchemy import select

    sql = compiled(select(TemperatureReading).options(temperature_series_columns()))
    assert "raw_payload" not in sql
    assert "temperature_readings.captured_at_utc" in sql
    assert "temperature_readings.temperature_c" in sql
    # The rest of the row is not read anywhere and must not travel.
    for column in ("device_id", "product_id", "target_temperature_c"):
        assert f"temperature_readings.{column}" not in sql, column


def test_fan_option_selects_exactly_the_rollup_columns() -> None:
    from sqlalchemy import select

    sql = compiled(select(FanStateReading).options(fan_series_columns()))
    assert "fan_state_readings.captured_at_utc" in sql
    assert "fan_state_readings.fan_on" in sql
    assert "fan_state_readings.fan_speed" in sql
    for column in ("reason", "action", "phase"):
        assert f"fan_state_readings.{column}" not in sql, column


def test_daily_metric_raw_payload_is_deliberately_still_loaded() -> None:
    """A floor, not an oversight — ``daily_metric_coverage`` reads this column.

    Deferring it would make ``complete_stress_avg`` raise, and deferring it
    *silently* would make a partial local-day aggregate look complete. Reducing
    it needs the coverage contract to change first.
    """
    from sqlalchemy import select

    import src.services.bulk_history_reads as module

    assert "DailyMetric" not in module.__all__
    assert "raw_payload" in compiled(select(DailyMetric))


# --------------------------------------------------------------------------
# The real call sites
# --------------------------------------------------------------------------


async def test_bedroom_rollup_issues_no_raw_payload_and_keeps_its_arithmetic() -> None:
    from src.services.insights import bedroom_driver_values_by_date

    player = _profile()
    # A single night, 22:00-06:00 local, warm enough to trip the warning band.
    night = [
        TemperatureReading(
            user_id=player.id,
            captured_at_utc=datetime(2026, 8, 19, 22, 0, tzinfo=UTC).replace(tzinfo=None)
            + timedelta(minutes=15 * i),
            temperature_c=temp,
            source="hive",
            raw_payload={},
        )
        for i, temp in enumerate([19.0, 20.5, 21.0, 20.0])
    ]
    fans = [
        FanStateReading(
            user_id=player.id,
            captured_at_utc=datetime(2026, 8, 19, 22, 0, tzinfo=UTC).replace(tzinfo=None)
            + timedelta(minutes=15 * i),
            phase="control",
            auto_enabled=True,
            fan_on=on,
            fan_speed=speed,
            action="apply",
        )
        for i, (on, speed) in enumerate([(True, 2), (True, 3), (False, None), (False, None)])
    ]
    session = RecordingSession({TemperatureReading: night, FanStateReading: fans})

    values = await bedroom_driver_values_by_date(
        session,  # type: ignore[arg-type]
        player,
        start=date(2026, 8, 20),
        end=date(2026, 8, 20),
    )

    for sql in sql_for(session, TemperatureReading):
        assert "raw_payload" not in sql
    assert session.statements, "the rollup issued no statements"

    rollup = values[date(2026, 8, 20)]
    assert rollup.mean_temp_c == pytest.approx(20.13, abs=0.01)
    assert rollup.min_temp_c == pytest.approx(19.0)
    assert rollup.max_temp_c == pytest.approx(21.0)
    assert rollup.peak_fan_speed == pytest.approx(3.0)


async def test_driver_records_read_no_sleep_raw_payload() -> None:
    from src.services.insights import InsightsService

    player = _profile()
    session = RecordingSession()
    await InsightsService(session)._driver_records(  # type: ignore[arg-type]
        player, start=date(2026, 5, 1), end=date(2026, 8, 30)
    )
    sleep_sql = sql_for(session, Sleep)
    assert sleep_sql, "no sleep statement was issued"
    for sql in sleep_sql:
        assert "raw_payload" not in sql
    for sql in sql_for(session, TemperatureReading):
        assert "raw_payload" not in sql


async def test_early_warning_reads_no_sleep_raw_payload() -> None:
    from src.services.insights import InsightsService

    session = RecordingSession()
    await InsightsService(session).early_warning(  # type: ignore[arg-type]
        _profile(), as_of=date(2026, 8, 30)
    )
    for sql in sql_for(session, Sleep):
        assert "raw_payload" not in sql


async def test_weekly_review_temperature_peaks_stay_correct_without_the_payload() -> None:
    from src.services.reviews import ReviewService

    user_id = uuid.uuid4()
    rows = [
        TemperatureReading(
            user_id=user_id,
            captured_at_utc=datetime(2026, 8, 19, 23, 0),
            temperature_c=21.5,
            source="hive",
            raw_payload={},
        ),
        TemperatureReading(
            user_id=user_id,
            captured_at_utc=datetime(2026, 8, 19, 20, 0),
            temperature_c=19.0,
            source="hive",
            raw_payload={},
        ),
    ]
    session = RecordingSession({TemperatureReading: rows})
    peaks = await ReviewService(session)._temperature_peaks(  # type: ignore[arg-type]
        user_id, date(2026, 8, 20), date(2026, 8, 20), "Europe/London"
    )
    assert peaks == {date(2026, 8, 20): 21.5}
    for sql in sql_for(session, TemperatureReading):
        assert "raw_payload" not in sql


async def test_trends_indoor_peaks_and_sleep_window_drop_the_payload() -> None:
    from src.services.trends import TrendsService

    user_id = uuid.uuid4()
    session = RecordingSession()
    service = TrendsService(session)  # type: ignore[arg-type]
    await service._indoor_peaks(user_id, date(2026, 8, 1), date(2026, 8, 30), "Europe/London")
    await service._rows(Sleep, user_id, date(2026, 8, 1), date(2026, 8, 30))
    await service._rows(DailyMetric, user_id, date(2026, 8, 1), date(2026, 8, 30))

    for sql in sql_for(session, TemperatureReading):
        assert "raw_payload" not in sql
    for sql in sql_for(session, Sleep):
        assert "raw_payload" not in sql
    # Same generic loader, opposite decision: the daily-metric payload stays.
    assert any("raw_payload" in sql for sql in sql_for(session, DailyMetric))


async def test_experiment_evaluation_sleep_rows_drop_the_payload() -> None:
    from src.services.experiment_evaluation import ExperimentEvaluationService

    session = RecordingSession()
    await ExperimentEvaluationService(session)._sleep_rows(  # type: ignore[arg-type]
        _profile(), start=date(2026, 5, 1), end=date(2026, 8, 30)
    )
    sleep_sql = sql_for(session, Sleep)
    assert sleep_sql
    for sql in sleep_sql:
        assert "raw_payload" not in sql


async def test_experiment_loop_night_contexts_drop_the_payload() -> None:
    from src.services.experiment_loop import ExperimentLoopService

    session = RecordingSession()
    await ExperimentLoopService(session)._night_contexts(  # type: ignore[arg-type]
        _profile(), [date(2026, 8, 28), date(2026, 8, 30)]
    )
    sleep_sql = sql_for(session, Sleep)
    assert sleep_sql
    for sql in sleep_sql:
        assert "raw_payload" not in sql
    for sql in sql_for(session, TemperatureReading):
        assert "raw_payload" not in sql


async def test_longitudinal_whole_history_read_drops_the_payload() -> None:
    from src.services.longitudinal_analysis import LongitudinalAnalysisService

    session = RecordingSession()
    await LongitudinalAnalysisService(session).assemble_nights(  # type: ignore[arg-type]
        _profile(), as_of_date=date(2026, 8, 30)
    )
    sleep_sql = sql_for(session, Sleep)
    assert sleep_sql
    for sql in sleep_sql:
        assert "raw_payload" not in sql


async def test_nightly_baseline_rebuild_drops_the_sleep_payload() -> None:
    """Batch 228 put this whole-history read on a nightly job (Decision #306)."""
    from src.services.metric_baselines import MetricBaselineBackfillService

    session = RecordingSession()
    await MetricBaselineBackfillService(session)._load_samples(  # type: ignore[arg-type]
        uuid.uuid4(), window_days=84, as_of=date(2026, 8, 30)
    )
    sleep_sql = sql_for(session, Sleep)
    assert sleep_sql
    for sql in sleep_sql:
        assert "raw_payload" not in sql


async def test_chat_context_sleep_history_drops_the_payload() -> None:
    from src.services.chat_context import ChatContextService

    session = RecordingSession()
    await ChatContextService(session)._sleep_history(  # type: ignore[arg-type]
        uuid.uuid4(), date(2026, 8, 30)
    )
    sleep_sql = sql_for(session, Sleep)
    assert sleep_sql
    for sql in sleep_sql:
        assert "raw_payload" not in sql


async def test_morning_overnight_temperature_rows_drop_the_payload() -> None:
    from src.services.morning_analysis import MorningAnalysisService

    session = RecordingSession()
    await MorningAnalysisService(session)._overnight_temperature_rows(  # type: ignore[arg-type]
        uuid.uuid4(), date(2026, 8, 30), "Europe/London"
    )
    sql = sql_for(session, TemperatureReading)
    assert sql
    for statement in sql:
        assert "raw_payload" not in statement
