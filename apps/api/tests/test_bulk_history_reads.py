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

``daily_metrics.raw_payload`` left the coverage path in Batch 280: the readers
that gate a stress or Body Battery figure on its local-day window now project
the ten facts that decide it and defer the document beside them. A bare
``select(DailyMetric)`` still ships it, so every coverage reader is driven here
and a full read added to any of them fails. The coach history lookup is
narrower still: it labels the observation phase and reads only typed recovery
fields, so its dedicated projection is tested separately.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import JSON, Integer, Select, String, create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, defer, mapped_column

from src.models.coaching import (
    DailyMetric,
    FanStateReading,
    Sleep,
    TemperatureReading,
    WeatherDaily,
)
from src.models.profile import Profile, UserRole
from src.services.bulk_history_reads import (
    daily_metric_reading_columns,
    fan_series_columns,
    select_day_aggregates,
    temperature_series_columns,
    weather_summary_columns,
    without_daily_metric_raw_payload,
    without_sleep_raw_payload,
)
from src.services.daily_metric_coverage import COVERAGE_FACTS, CoverageSource

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


def test_a_bare_daily_metric_read_still_ships_the_document() -> None:
    """The floor every new reader starts from, which is why the readers are driven below.

    Batch 280 changed the coverage contract so no coverage reader needs the
    document, but ``select(DailyMetric)`` is still the default idiom and still
    selects it. The contract tests below are what keeps it off the coverage path.
    """
    from sqlalchemy import select

    assert selects_whole_daily_payload(compiled(select(DailyMetric)))


def test_coach_daily_metric_projection_leaves_provider_payload_behind() -> None:
    """The tool labels the phase instead of inferring full-day source coverage."""
    from sqlalchemy import select

    sql = compiled(select(DailyMetric).options(daily_metric_reading_columns()))
    assert "raw_payload" not in sql
    for column in (
        "daily_metrics.calendar_date",
        "daily_metrics.phase",
        "daily_metrics.readiness_score",
        "daily_metrics.hrv_last_night_avg_ms",
        "daily_metrics.resting_heart_rate_bpm",
        "daily_metrics.body_battery_end",
    ):
        assert column in sql, column


def test_thermal_weather_projection_leaves_provider_payload_behind() -> None:
    from sqlalchemy import select

    sql = compiled(select(WeatherDaily).options(weather_summary_columns()))
    assert "raw_payload" not in sql
    for column in (
        "weather_daily.calendar_date",
        "weather_daily.overnight_low_c",
        "weather_daily.overnight_wind_gust_mph",
    ):
        assert column in sql, column


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
        user_id, date(2026, 8, 20), date(2026, 8, 20), "Europe/London", []
    )
    # Batch 268: the 23:00 UTC reading is 00:00 local and inside the night; the
    # 20:00 UTC one is 21:00 local and is not, so it no longer contributes.
    assert peaks[date(2026, 8, 20)].peak_c == 21.5
    assert peaks[date(2026, 8, 20)].sample_count == 1
    assert peaks[date(2026, 8, 20)].window_source == "night_fallback"
    for sql in sql_for(session, TemperatureReading):
        assert "raw_payload" not in sql
    # The shared night-window leaf is pure and must not have issued a lookup of
    # its own: the caller hands it the sleep rows it already loaded.
    assert not sql_for(session, Sleep)


async def test_trends_indoor_peaks_and_sleep_window_drop_the_payload() -> None:
    from src.services.trends import TrendsService

    user_id = uuid.uuid4()
    session = RecordingSession()
    service = TrendsService(session)  # type: ignore[arg-type]
    await service._indoor_peaks(user_id, date(2026, 8, 1), date(2026, 8, 30), "Europe/London", [])
    await service._rows(Sleep, user_id, date(2026, 8, 1), date(2026, 8, 30))
    await service._rows(DailyMetric, user_id, date(2026, 8, 1), date(2026, 8, 30))

    for sql in sql_for(session, TemperatureReading):
        assert "raw_payload" not in sql
    for sql in sql_for(session, Sleep):
        assert "raw_payload" not in sql
    # Same generic loader, opposite decision: the daily-metric payload stays.
    # Not for coverage any more (Batch 280) — trends reads four typed columns —
    # but left for a measured batch of its own rather than swept in here.
    assert any(selects_whole_daily_payload(sql) for sql in sql_for(session, DailyMetric))


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


async def test_acute_physiology_history_pins_its_projection_and_its_phase() -> None:
    """Batch 271 widened this loader by two columns; pin what it may carry.

    Two things are asserted, and they fail for different reasons. The projection
    must name the Garmin band (271 reads it) and must still exclude
    ``raw_payload`` — a widening that reached the payload would restore a
    Batch 235-class pooler transfer over an 84-day window. And the query must
    still filter to the morning phase: ``uq_daily_metrics_user_date_phase``
    (Batch 205) puts two rows on every date, and a recalibration detector that
    compared a morning row against a settled one would invent a movement.

    This loader was **not** covered here before Batch 271.
    """
    from src.services.morning_analysis import MorningAnalysisService

    session = RecordingSession()
    await MorningAnalysisService(session)._acute_physiology_history(  # type: ignore[arg-type]
        uuid.uuid4(), date(2026, 9, 18)
    )
    metric_sql = sql_for(session, DailyMetric)
    assert metric_sql
    for sql in metric_sql:
        assert "raw_payload" not in sql
        assert "hrv_baseline_low_ms" in sql
        assert "hrv_baseline_high_ms" in sql
        assert "hrv_last_night_avg_ms" in sql
        assert "phase" in sql
    for sql in sql_for(session, Sleep):
        assert "raw_payload" not in sql


# --------------------------------------------------------------------------
# Batch 280: the coverage path leaves Garmin's daily document behind
# --------------------------------------------------------------------------

_WHOLE_DAILY_PAYLOAD = re.compile(r"daily_metrics\.raw_payload\s*(,|FROM\b|$)")


def selects_whole_daily_payload(sql: str) -> bool:
    """True when a statement ships ``daily_metrics.raw_payload`` as a column.

    The projection *reads* the column server-side (``raw_payload || '{}'``) but
    never selects it, so a bare mention of the name is not the test; a mention as
    a selected column is.
    """
    return bool(_WHOLE_DAILY_PAYLOAD.search(sql))


def test_the_projection_reads_the_document_once_and_ships_none_of_it() -> None:
    """One read per row, and the shape that guarantees it (280.2).

    Written as one JSONB operator per fact against the stored column, the same
    projection read the TOASTed document sixteen times a row and took 943 ms for
    Mark's 550 rows — slower than shipping them. Reading it once through the
    ``LATERAL`` fence took 35-78 ms (production, 2026-09-23).
    """
    sql = compiled(select_day_aggregates())

    assert not selects_whole_daily_payload(sql)
    assert sql.count("daily_metrics.raw_payload") == 1
    assert "JOIN LATERAL" in sql
    assert "OFFSET" in sql
    for fact in COVERAGE_FACTS:
        assert f"AS {fact.field}" in sql, fact.field
    for column in ("calendar_date", "phase", "stress_avg", "body_battery_charged"):
        assert f"daily_metrics.{column}" in sql, column


def test_the_typed_read_beside_it_drops_only_the_document() -> None:
    from sqlalchemy import select

    sql = compiled(select(DailyMetric).options(without_daily_metric_raw_payload()))
    assert "raw_payload" not in sql
    for column in (
        "daily_metrics.phase",
        "daily_metrics.readiness_score",
        "daily_metrics.hrv_last_night_avg_ms",
        "daily_metrics.hrv_weekly_avg_ms",
        "daily_metrics.resting_heart_rate_bpm",
        "daily_metrics.stress_avg",
        "daily_metrics.body_battery_charged",
    ):
        assert column in sql, column


def _assert_leaves_the_daily_document_behind(session: RecordingSession) -> None:
    metric_sql = sql_for(session, DailyMetric)
    assert metric_sql, "the reader issued no daily_metrics statement"
    for sql in metric_sql:
        assert not selects_whole_daily_payload(sql), sql


async def test_review_rollup_leaves_the_daily_document_behind() -> None:
    """280.5: a ``select(DailyMetric)`` added to the review rollup fails here."""
    from src.services.reviews import ReviewService

    session = RecordingSession()
    await ReviewService(session)._build_rollup(  # type: ignore[arg-type]
        _profile(), "week", date(2026, 9, 14), date(2026, 9, 20)
    )
    _assert_leaves_the_daily_document_behind(session)


async def test_driver_records_leave_the_daily_document_behind() -> None:
    from src.services.insights import InsightsService

    session = RecordingSession()
    await InsightsService(session)._driver_records(  # type: ignore[arg-type]
        _profile(), start=date(2026, 5, 26), end=date(2026, 9, 22)
    )
    _assert_leaves_the_daily_document_behind(session)


async def test_nightly_baseline_rebuild_leaves_the_daily_document_behind() -> None:
    """The whole-history read — every stored document, every night, before 280."""
    from src.services.metric_baselines import MetricBaselineBackfillService

    session = RecordingSession()
    await MetricBaselineBackfillService(session)._load_samples(  # type: ignore[arg-type]
        uuid.uuid4(), window_days=84, as_of=date(2026, 9, 22)
    )
    _assert_leaves_the_daily_document_behind(session)


async def test_morning_aggregate_reads_leave_the_daily_document_behind() -> None:
    """Yesterday's closed-day cost and today's settled aggregates.

    The wake row itself is still read whole — fitness age and the training
    fields come out of its document — so ``_daily_metric`` is deliberately not
    driven here. It is one row, and it is named in the Batch 280 ledger row.
    """
    from src.services.morning_analysis import MorningAnalysisService

    session = RecordingSession()
    service = MorningAnalysisService(session)  # type: ignore[arg-type]
    await service._day_aggregate_metric(uuid.uuid4(), date(2026, 9, 22))
    await service._yesterday_load(uuid.uuid4(), date(2026, 9, 22), "Europe/London", [])
    _assert_leaves_the_daily_document_behind(session)


# --------------------------------------------------------------------------
# The SQLAlchemy behaviour the deferred reads rely on
# --------------------------------------------------------------------------


class _IdentityBase(DeclarativeBase):
    pass


class _Observation(_IdentityBase):
    __tablename__ = "observation"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


def _identity_session() -> Session:
    engine = create_engine("sqlite://")
    _IdentityBase.metadata.create_all(engine)
    with Session(engine) as seed:
        seed.add(_Observation(id=1, name="wake", payload={"k": 1}))
        seed.commit()
    return Session(engine)


def test_a_later_whole_row_query_fills_a_column_an_earlier_read_deferred() -> None:
    """Why a deferred history read is safe beside a whole-row reader (Batch 280).

    The morning read defers nothing on the wake row but shares a session with
    history reads that do. SQLAlchemy fills the unloaded attribute of an object
    it already holds when a later query selects the whole row, so the whole-row
    reader gets its document. Pinned because the design depends on it and an
    upgrade could change it.
    """
    from sqlalchemy import select

    with _identity_session() as session:
        deferred = (
            session.execute(
                select(_Observation).options(defer(_Observation.payload, raiseload=True))
            )
            .scalars()
            .one()
        )
        whole = session.execute(select(_Observation)).scalars().one()
        assert whole is deferred
        assert whole.payload == {"k": 1}


def test_reaching_a_deferred_column_without_a_query_still_raises() -> None:
    """The one path that does fail, loudly: ``session.get`` on an identity it holds.

    ``get`` answers from the identity map without a query, so the deferred column
    is never filled — and ``raiseload`` makes that an error rather than a lazy load.
    (The map holds objects weakly: once nothing references the deferred read,
    ``get`` queries again and loads the whole row.)
    """
    from sqlalchemy import select
    from sqlalchemy.exc import InvalidRequestError

    with _identity_session() as session:
        deferred = (
            session.execute(
                select(_Observation).options(defer(_Observation.payload, raiseload=True))
            )
            .scalars()
            .one()
        )
        held = session.get(_Observation, 1)
        assert held is deferred
        with pytest.raises(InvalidRequestError):
            _ = held.payload


# --------------------------------------------------------------------------
# Postgres: the projection reads every fact exactly as Python does
# --------------------------------------------------------------------------


_VALUE_SHAPES: list[Any] = [
    [],
    [[1785452400000, 12]],
    {},
    {"a": 1},
    "",
    "x",
    0,
    1,
    0.0,
    2.5,
    True,
    False,
    None,
]


def _documents() -> list[Any]:
    documents: list[Any] = [
        {
            "stress": {
                "avgStressLevel": 28,
                "startTimestampLocal": "2026-07-31T00:00:00.0",
                "endTimestampLocal": "2026-08-01T00:00:00.0",
            },
            "stats": {
                "wellnessStartTimeLocal": "2026-07-31T00:00:00.0",
                "wellnessEndTimeLocal": "2026-08-01T00:00:00.0",
            },
            "body_battery": {
                "charged": 81,
                "drained": 70,
                "bodyBatteryValuesArray": [[1785452400000, 12]],
                "startTimestampLocal": "2026-07-31T00:00:00.0",
                "endTimestampLocal": "2026-07-31T08:44:00.0",
            },
        },
        {},
        {"stress": [], "body_battery": "x", "stats": None},
        [1, 2],
    ]
    for value in _VALUE_SHAPES:
        documents.append(
            {
                "stress": {"avgStressLevel": value, "startTimestampLocal": value},
                "stats": {"wellnessEndTimeLocal": value},
                "body_battery": {
                    "bodyBatteryValuesArray": value,
                    "charged": value,
                    "drained": value,
                    "endTimestampLocal": value,
                },
            }
        )
    return documents


@pytest.mark.asyncio
async def test_the_projection_reads_every_fact_as_python_does(
    db_conn: AsyncConnection,
) -> None:
    """280.5 against real Postgres: projected facts equal ``from_document`` for every shape.

    Every JSON type in the truthiness position, JSON null, missing keys, sections
    that are not objects and a root that is not an object — the projection must
    agree with the Python reading on all of them, not just on the one shape
    production stores today.
    """

    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    documents = _documents()
    first_day = date(2026, 1, 1)
    async with session_factory() as session:
        session.add(
            Profile(
                id=user_id,
                display_name="Coverage projection",
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
            )
        )
        await session.flush()
        for offset, document in enumerate(documents):
            session.add(
                DailyMetric(
                    user_id=user_id,
                    calendar_date=first_day + timedelta(days=offset),
                    phase="settled",
                    raw_payload=document,
                )
            )
        await session.flush()

        rows = (
            await session.execute(
                select_day_aggregates()
                .where(DailyMetric.user_id == user_id)
                .order_by(DailyMetric.calendar_date)
            )
        ).all()

    assert len(rows) == len(documents)
    for row, document in zip(rows, documents, strict=True):
        assert CoverageSource.from_row(row) == CoverageSource.from_document(document), document
