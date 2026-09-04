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
  ``Sleep`` objects and every existing calculation is untouched.
* :func:`temperature_series_columns` / :func:`fan_series_columns` **project**,
  because those readers want two or three columns out of the row and the
  payload is the rest of it.

Both pass ``raiseload=True``. An unloaded attribute would otherwise emit a lazy
SELECT, which under an async session fails as ``MissingGreenlet`` far from the
cause; this way an unforeseen reader raises immediately, naming the attribute.

**Deferring is safe only where nothing in the same session reads the column**,
because SQLAlchemy's identity map hands a later query the object it already
holds. That is why ``daily_metrics.raw_payload`` is *not* deferred anywhere:
``daily_metric_coverage`` reads it to decide whether a stress or Body Battery
aggregate covers the whole local day, and ``morning_analysis`` reads it in the
same session that builds the chronic-pattern window. Reducing that one needs the
coverage contract to change first.
"""

from __future__ import annotations

from sqlalchemy.orm import defer, load_only
from sqlalchemy.orm.interfaces import ORMOption

from src.models.coaching import ActivityTimeSeries, FanStateReading, Sleep, TemperatureReading

__all__ = [
    "activity_timeseries_columns",
    "fan_series_columns",
    "temperature_series_columns",
    "without_sleep_raw_payload",
]

#: The four JSONB-carrying models. **Any multi-row read of one of these belongs
#: here** — a bare ``select(Model)`` over them is the idiom that caused both of
#: this app's egress incidents (Batch 232's pooler refusals, Batch 235's 34.8 GB),
#: and it is still the default way to read a row in this codebase (Batch 253,
#: CR236-13). ``batch-verify`` asks the question once per batch so it is checked
#: rather than remembered.
JSONB_CARRYING_MODELS = ("sleep", "daily_metrics", "temperature_readings", "analyses")


def without_sleep_raw_payload() -> ORMOption:
    """Load a ``Sleep`` row without the ~105 KB stored Garmin sleep document.

    Every other column still loads, so consumers keep the typed stage, SpO2,
    HRV and stress reads they actually correlate on. The one reader of
    ``raw_payload`` is the hypnogram on ``GET /bedroom/overnight``, which
    fetches its single night by date and shares a session with none of these.
    """
    return defer(Sleep.raw_payload, raiseload=True)


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
