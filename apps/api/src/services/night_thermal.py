"""The bedroom peak, on the night it actually happened (Batch 268).

``ReviewService._temperature_peaks`` and ``TrendService._indoor_peaks`` were the
same function twice, and both had the same defect: they attributed *every*
reading in the period to a night — anything before 18:00 local to that day,
anything after to the next — and kept the maximum. There was no sleep-window
filter anywhere in either, so a 21.4 °C afternoon in an empty house was reported
to Mark as his bedroom overnight peak. Measured across 7–20 September 2026 the
two contested weeks read 20.0–21.4 °C against true sleep-window peaks of
17.9–19.7 °C, and the weekly review told him "5 of 7 nights showed thermal
disruption" on nights that never reached 20 °C at all.

The morning brief has never been disputed on the same figures, because it asks a
different question. This module is that question, extracted once so the two
surfaces cannot drift apart again:

* :func:`bedroom_overnight.night_window` is the canonical clock window — 21:30
  local to 09:00 the next morning — and it is what "night" means everywhere else
  in this app.
* When the night has a ``sleep`` row with a usable window, narrow to the hours he
  was actually asleep, exactly as ``coach_sections.thermal_review`` does.
* Report *which* of those two was used, so a fallback night is distinguishable
  from a measured one rather than silently equivalent.

Pure: it takes rows the caller has already loaded and issues no query of its own.
Both callers already read their ``sleep`` rows under
``bulk_history_reads.without_sleep_raw_payload()``, which defers only
``raw_payload`` and therefore keeps ``sleep_start_utc``/``sleep_end_utc``
available, so this needs no widening of anybody's query and no new egress.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.models.coaching import Sleep, TemperatureReading
from src.services.bedroom_overnight import night_window

WindowSource = Literal["sleep", "night_fallback"]


@dataclass(frozen=True)
class NightIndoorPeak:
    """One night's indoor peak, and the window it was measured over.

    ``window_source`` is the honesty half. ``"sleep"`` means the peak is bounded
    by the hours Garmin recorded him asleep; ``"night_fallback"`` means no usable
    sleep row existed and the bare 21:30–09:00 clock window was used instead. The
    two are not equally trustworthy and the rollup should not present them as if
    they were.
    """

    peak_c: float
    window_source: WindowSource
    sample_count: int


def night_indoor_peaks(
    temperature_rows: Sequence[TemperatureReading],
    sleeps: Sequence[Sleep],
    *,
    start: date,
    end: date,
    timezone_name: str,
) -> dict[date, NightIndoorPeak]:
    """Peak indoor temperature per local night, keyed by the **wake** date.

    ``start``/``end`` are wake dates, inclusive. A night is attributed to the
    morning it ends on, which is the convention every other bedroom surface uses
    and the one the review and trend rollups already key on.

    Nights with no readings inside their window are absent from the result rather
    than present with ``None`` — an unmeasured night is not a cold one, and the
    disruption count must not be able to read it as either.
    """
    tz = _zone(timezone_name)
    sleep_by_wake_date = {row.calendar_date: row for row in sleeps}

    peaks: dict[date, NightIndoorPeak] = {}
    wake_date = start
    while wake_date <= end:
        window_start, window_end = night_window(wake_date - timedelta(days=1), tz)
        source: WindowSource = "night_fallback"
        sleep_row = sleep_by_wake_date.get(wake_date)
        if sleep_row is not None:
            narrowed = _sleep_window(sleep_row)
            if narrowed is not None:
                # Intersect rather than replace: a sleep row that starts before
                # 21:30 or ends after 09:00 must not drag daytime readings back
                # in, which is the whole defect this module exists to remove.
                sleep_start, sleep_end = narrowed
                window_start = max(window_start, sleep_start)
                window_end = min(window_end, sleep_end)
                source = "sleep"

        values = [
            float(row.temperature_c)
            for row in temperature_rows
            if row.temperature_c is not None
            and window_start <= _naive_utc(row.captured_at_utc) <= window_end
        ]
        if values:
            peaks[wake_date] = NightIndoorPeak(
                peak_c=max(values),
                window_source=source,
                sample_count=len(values),
            )
        wake_date += timedelta(days=1)
    return peaks


def peak_values(peaks: Mapping[date, NightIndoorPeak]) -> dict[date, float]:
    """Just the temperatures, for callers that only need the number."""
    return {day: peak.peak_c for day, peak in peaks.items()}


def _sleep_window(row: Sleep) -> tuple[datetime, datetime] | None:
    start = row.sleep_start_utc
    end = row.sleep_end_utc
    if start is None or end is None:
        return None
    start_naive = _naive_utc(start)
    end_naive = _naive_utc(end)
    if end_naive <= start_naive:
        return None
    return (start_naive, end_naive)


def _naive_utc(moment: datetime) -> datetime:
    """UTC-naive, whichever way the row arrived.

    The ``*_utc`` columns are naive by convention, but a caller constructing a
    fixture with an explicit ``tzinfo=UTC`` is comparing against naive bounds and
    would otherwise raise at the comparison rather than fail a test readably.
    """
    if moment.tzinfo is None:
        return moment
    return moment.astimezone(UTC).replace(tzinfo=None)


def _zone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")
