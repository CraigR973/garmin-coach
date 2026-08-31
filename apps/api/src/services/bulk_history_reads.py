"""Reading a history window without shipping the provider payload with it.

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

from src.models.coaching import FanStateReading, Sleep, TemperatureReading

__all__ = [
    "fan_series_columns",
    "temperature_series_columns",
    "without_sleep_raw_payload",
]


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
