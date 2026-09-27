"""Reading a history window without shipping the provider payload with it.

**This module is the documented entry point for any multi-row read of a
JSONB-carrying model** — ``sleep``, ``daily_metrics``, ``temperature_readings``,
``analyses`` (Batch 253, CR236-13). It is not a lint rule, because the
false-positive rate on ``select(Model)`` would be unmanageable; it is a named
place plus a question ``batch-verify`` now asks once per batch. The reason it
needs saying at all: ``select(Model)`` is still the default way to read a row in
this codebase, so new full-row reads kept appearing — including in code written
*after* Batch 235 built this module to stop them.

A bare ``select(Sleep)`` over a 120-night window is not a small query. Every
model here carries the untouched Garmin/Hive response in a JSONB column, and
JSONB travels the wire **uncompressed** — Postgres stores it TOAST-compressed
but sends the expanded document. Measured in production on 2026-08-30:

===================== ============== ================ =========================
Column                 stored bytes   bytes on wire    what the readers use
===================== ============== ================ =========================
``sleep.raw_payload``          12,670          105,550   nothing
``temperature_readings
.raw_payload``                  1,314            2,308   nothing
===================== ============== ================ =========================

So a single 120-night driver-correlation read moved ~12.7 MB to compute a
Pearson coefficient over a dozen typed floats, and the bedroom rollup moved the
*entire* temperature table (~16.6 MB) to average a column of temperatures. That
is the whole of the 2026-08-30 Shared Pooler egress incident: the bytes never
appear in ``EgressBudgetMiddleware``, which counts HTTP responses, because they
travel in the other direction — database to application.

The two shapes below are deliberate and different:

* :func:`without_sleep_raw_payload` **defers** one column, so callers keep real
  ``Sleep`` objects and every existing calculation is untouched;
  :func:`without_activity_raw_summary` does the same for ``activities`` (Batch
  281), except on the loaders that feed the ride read.
* :func:`temperature_series_columns` / :func:`fan_series_columns` **project**,
  because those readers want two or three columns out of the row and the
  payload is the rest of it.
* :func:`daily_metric_reading_columns` and :func:`weather_summary_columns`
  project the typed history that the coach may fetch. They deliberately do not
  promise whole-day coverage from an unlabelled morning row: the caller carries
  the metric phase, while the weather summary uses only promoted columns.

Both pass ``raiseload=True``. An unloaded attribute would otherwise emit a lazy
SELECT, which under an async session fails as ``MissingGreenlet`` far from the
cause; this way an unforeseen reader raises immediately, naming the attribute.

**What the identity map does with a deferred column** — measured on SQLAlchemy
2.0.51 for Batch 280, correcting what this paragraph used to claim. A later
query that selects the whole row *does* fill in a column an earlier query
deferred on the same object: SQLAlchemy populates the unloaded attributes of an
object it already holds. What fails is reaching the column *without* such a
query — ``session.get()`` on an object already in the identity map, or an object
handed on from the deferred read. So a deferred read is safe beside a whole-row
reader in the same session as long as that reader issues its own query.
``test_bulk_history_reads`` pins the behaviour, so an upgrade that changes it
fails CI rather than a coaching path.

``daily_metrics.raw_payload`` (Batch 280). The coverage readers no longer need
it: :func:`select_day_aggregates` projects the ten facts a coverage decision is
made from (``daily_metric_coverage.COVERAGE_FACTS``) server-side, and the typed
reads beside it defer the document with :func:`without_daily_metric_raw_payload`.
Batch 285 did the same for the four history windows that still shipped it —
trends (every stored row, on every coach question and Trends page), the
longitudinal nights, the chronic-pattern window and the early warning — none of
which reads the document. What still loads it is one row at a time: the
morning's wake row and the coach's view of today (both read the training fields
out of it, each with its own query), the Garmin writers, and single-row lookups
that take the whole row by habit.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Numeric, Select, case, cast, false, func, literal_column, select, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import defer, load_only
from sqlalchemy.orm.interfaces import ORMOption
from sqlalchemy.sql.elements import ColumnElement, Label

from src.models.coaching import (
    Activity,
    ActivityTimeSeries,
    Analysis,
    DailyMetric,
    FanStateReading,
    Sleep,
    TemperatureReading,
    WeatherDaily,
)
from src.services.daily_metric_coverage import COVERAGE_FACTS, CoverageFact

__all__ = [
    "activity_timeseries_columns",
    "daily_metric_reading_columns",
    "fan_series_columns",
    "select_day_aggregates",
    "select_morning_calls",
    "temperature_series_columns",
    "weather_summary_columns",
    "without_activity_raw_summary",
    "without_daily_metric_raw_payload",
    "without_sleep_raw_payload",
]

#: The four JSONB-carrying models. **Any multi-row read of one of these belongs
#: here** — a bare ``select(Model)`` over them is the idiom that caused both of
#: this app's egress incidents (Batch 232's pooler refusals, Batch 235's 34.8 GB),
#: and it is still the default way to read a row in this codebase (Batch 253,
#: CR236-13). ``batch-verify`` asks the question once per batch so it is checked
#: rather than remembered.
JSONB_CARRYING_MODELS = (
    "sleep",
    "daily_metrics",
    "temperature_readings",
    "analyses",
    # Batch 281: ~4.6 KB of Garmin summary per row, 7.3 GB of reads in 92 days.
    "activities",
)


def without_sleep_raw_payload() -> ORMOption:
    """Load a ``Sleep`` row without the ~105 KB stored Garmin sleep document.

    Every other column still loads, so consumers keep the typed stage, SpO2,
    HRV and stress reads they actually correlate on. The one reader of
    ``raw_payload`` is the hypnogram on ``GET /bedroom/overnight``, which
    fetches its single night by date and shares a session with none of these.
    """
    return defer(Sleep.raw_payload, raiseload=True)


def without_daily_metric_raw_payload() -> ORMOption:
    """Load a ``DailyMetric`` row without Garmin's ~40 KB daily document (Batch 280).

    For the typed reads that sit beside :func:`select_day_aggregates`: the
    recovery readings come off the row, the coverage facts off the projection,
    and the document stays in the database.
    """
    return defer(DailyMetric.raw_payload, raiseload=True)


def without_activity_raw_summary() -> ORMOption:
    """Load an ``Activity`` row without Garmin's ~4.6 KB activity summary (Batch 281).

    ``activities.raw_summary`` is read in exactly two places, and every other
    loader takes typed columns only:

    * ``garmin_sync`` carries ``activitySplits`` forward on an upsert, from a
      row it loads by ``garmin_activity_id`` itself.
    * the ride read (``post_workout_analysis``) grades intervals on
      ``activitySplits.lapDTOs`` — from the object it is *handed*. So the two
      loaders that hand it one keep the whole row: its own
      ``pending_ride_activities``, and ``DailyLoopService._activity``, whose
      object the check-in route's ``session.get`` receives from the identity map.

    Deferred rather than projected, so callers keep real ``Activity`` objects
    and every calculation over them is untouched; ``raiseload`` makes a reader
    that does need the summary fail at the attribute, not in a lazy load.
    """
    return defer(Activity.raw_summary, raiseload=True)


def select_day_aggregates() -> Select[Any]:
    """The running local-day totals and their coverage facts, projected (Batch 280).

    One row per observation: ``calendar_date``, ``phase``, the four aggregate
    columns, and the ten :data:`~src.services.daily_metric_coverage.COVERAGE_FACTS`
    labelled by field name — about two hundred bytes in place of a forty-kilobyte
    document. Callers add their own ``where``/``order_by``/``limit`` and build
    each result with ``DayAggregates.from_row``.

    **The document is read once per row, and the shape of the SQL is what makes
    that true.** Every JSONB operator applied to the stored column fetches and
    decompresses the whole TOASTed document again, so writing the ten facts
    against ``daily_metrics.raw_payload`` directly costs sixteen reads a row —
    943 ms for Mark's 550 rows, measured on production on 2026-09-23, which is
    slower than shipping the documents (345-359 ms to render them as text).
    Instead a ``LATERAL`` subquery reads the document once into memory and every
    fact is taken from that copy: 35-78 ms for the same rows across runs.
    ``OFFSET 0`` stops the planner folding the subquery back into sixteen reads,
    and ``|| '{}'`` hands back the document already read into memory —
    PostgreSQL returns the non-empty operand of an empty concatenation as is.
    Unlike ``jsonb_to_record``, which would also read it once, it cannot raise on
    a document whose root is not an object, so the projection is as total as
    ``CoverageSource.from_document``.
    """
    document = (
        select(
            DailyMetric.raw_payload.op("||", return_type=JSONB)(
                literal_column("'{}'::jsonb", type_=JSONB)
            ).label("document")
        )
        .correlate(DailyMetric)
        .offset(0)
        .lateral("coverage_document")
    )
    return (
        select(
            DailyMetric.calendar_date,
            DailyMetric.phase,
            DailyMetric.stress_avg,
            DailyMetric.body_battery_charged,
            DailyMetric.body_battery_drained,
            DailyMetric.body_battery_end,
            *(_coverage_fact(document.c.document, fact) for fact in COVERAGE_FACTS),
        )
        .select_from(DailyMetric)
        .join(document, true())
    )


def select_morning_calls() -> Select[Any]:
    """What a stored morning read decided about its day, projected (Batch 289).

    One row per stored ``morning`` analysis: ``subject_date``,
    ``generated_at_utc``, the typed ``verdict``, and five fields of the read's
    frozen packet — the verdict's ``reasons``, its ``verdictAdjustment``, whether
    an acute signal ruled out riding (``requiresBikeRest``), ``restDay`` and the
    ``plannedWorkouts`` the morning saw. About a kilobyte a row, against a packet
    that averages **64,812 characters** (measured 2026-09-26); the coach asks for
    seven of them on every question, so loading them whole would ship ~450 KB a
    turn to read eight fields. Callers add their own ``where``/``order_by``.

    The packet is read once per row by the same ``LATERAL`` + ``OFFSET 0`` shape
    as :func:`select_day_aggregates`, for the same reason: every JSONB operator
    applied to the stored column re-reads the TOASTed document.
    """
    document = (
        select(
            Analysis.context_packet.op("||", return_type=JSONB)(
                literal_column("'{}'::jsonb", type_=JSONB)
            ).label("document")
        )
        .correlate(Analysis)
        .offset(0)
        .lateral("morning_document")
    )
    packet = document.c.document
    return (
        select(
            Analysis.subject_date,
            Analysis.generated_at_utc,
            Analysis.verdict,
            packet[("verdict", "reasons")].label("reasons"),
            packet[("verdict", "verdictAdjustment")].label("verdict_adjustment"),
            packet[("verdict", "acutePhysiology", "requiresBikeRest")].label("requires_bike_rest"),
            packet[("restDay",)].label("rest_day"),
            packet[("plannedWorkouts",)].label("planned_workouts"),
        )
        .select_from(Analysis)
        .join(document, true())
        .where(Analysis.analysis_type == "morning")
    )


def _coverage_fact(document: ColumnElement[Any], fact: CoverageFact) -> Label[Any]:
    """One coverage fact, read in SQL exactly as ``CoverageSource.from_document`` reads it.

    ``#>`` / ``#>>`` return NULL for a missing key, for a section that is not an
    object, and (``#>>``) for a JSON null — the same three cases the Python side
    reads as ``None``.
    """
    element = document[(fact.section, fact.key)]
    text: ColumnElement[Any] = element.astext
    kind = func.jsonb_typeof(element)
    if fact.kind == "reported":
        return text.is_not(None).label(fact.field)
    if fact.kind == "text":
        return case({"string": text}, value=kind).label(fact.field)
    # ``truthy``: Python's ``bool()`` over every JSON type, so the boolean says
    # what the array test said without shipping — or inventing — the array.
    return case(
        {
            "array": func.jsonb_array_length(element) > 0,
            "object": text != "{}",
            "string": text != "",
            "number": cast(text, Numeric) != 0,
            "boolean": text == "true",
        },
        value=kind,
        else_=false(),
    ).label(fact.field)


def temperature_series_columns() -> ORMOption:
    """Load only the two columns an indoor-temperature series is read for.

    ``captured_at_utc`` places the reading in a night; ``temperature_c`` is the
    measurement. Nothing in the app reads ``TemperatureReading.raw_payload``.
    """
    return load_only(
        TemperatureReading.captured_at_utc,
        TemperatureReading.temperature_c,
        raiseload=True,
    )


def daily_metric_reading_columns() -> ORMOption:
    """Load the typed recovery observation used by the coach history lookup.

    Other history consumers still load ``raw_payload`` because they evaluate
    complete-day aggregate coverage from Garmin's source window. The coach tool
    instead labels every row as ``morning`` or ``settled`` and describes Body
    Battery relative to that observation, so moving the large provider payload
    would add egress without strengthening its claim.
    """
    return load_only(
        DailyMetric.calendar_date,
        DailyMetric.phase,
        DailyMetric.recorded_at_utc,
        DailyMetric.readiness_score,
        DailyMetric.readiness_level,
        DailyMetric.readiness_sleep_score,
        DailyMetric.recovery_time_min,
        DailyMetric.acute_load,
        DailyMetric.training_status,
        DailyMetric.hrv_last_night_avg_ms,
        DailyMetric.hrv_weekly_avg_ms,
        DailyMetric.hrv_status,
        DailyMetric.hrv_baseline_low_ms,
        DailyMetric.hrv_baseline_high_ms,
        DailyMetric.resting_heart_rate_bpm,
        DailyMetric.stress_avg,
        DailyMetric.body_battery_charged,
        DailyMetric.body_battery_drained,
        DailyMetric.body_battery_end,
        raiseload=True,
    )


def weather_summary_columns() -> ORMOption:
    """Load the promoted weather fields used beside a thermal-night review."""
    return load_only(
        WeatherDaily.calendar_date,
        WeatherDaily.source,
        WeatherDaily.temp_high_c,
        WeatherDaily.temp_low_c,
        WeatherDaily.overnight_low_c,
        WeatherDaily.overnight_wind_max_mph,
        WeatherDaily.overnight_wind_gust_mph,
        WeatherDaily.overnight_wind_direction_deg,
        WeatherDaily.overnight_relative_humidity_mean_pct,
        WeatherDaily.precipitation_mm,
        WeatherDaily.sunrise_utc,
        WeatherDaily.sunset_utc,
        raiseload=True,
    )


def fan_series_columns() -> ORMOption:
    """Load only the columns an overnight fan rollup is read for.

    Narrower than the ``/bedroom/overnight`` chart, which also renders the
    decision (``action``/``reason``) and so selects the whole row.
    """
    return load_only(
        FanStateReading.captured_at_utc,
        FanStateReading.fan_on,
        FanStateReading.fan_speed,
        raiseload=True,
    )


def activity_timeseries_columns() -> ORMOption:
    """Load only the typed sample columns the post-activity analysers read.

    Batch 253 (DS237-17). ``ActivityTimeSeries.raw_metrics`` is a per-sample JSONB
    document retained in full for outdoor rides, and no analyser reads it — but
    ``select(ActivityTimeSeries)`` materialised one for every sample of every
    activity. Deferred rather than ``raiseload``: this is a per-request read
    rather than a history window, and a future caller that genuinely wants the
    raw sample should get it lazily rather than an exception.
    """
    return load_only(
        ActivityTimeSeries.sample_index,
        ActivityTimeSeries.timestamp_utc,
        ActivityTimeSeries.elapsed_sec,
        ActivityTimeSeries.moving_duration_sec,
        ActivityTimeSeries.distance_m,
        ActivityTimeSeries.power_watts,
        ActivityTimeSeries.heart_rate_bpm,
        ActivityTimeSeries.cadence_rpm,
        ActivityTimeSeries.respiration,
        ActivityTimeSeries.performance_condition,
        ActivityTimeSeries.available_stamina,
        ActivityTimeSeries.potential_stamina,
        ActivityTimeSeries.speed_mps,
        ActivityTimeSeries.air_temperature_c,
    )
