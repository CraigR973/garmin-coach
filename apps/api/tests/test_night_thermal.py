"""Batch 268 — the bedroom peak is measured over the night, not the day.

Every number in ``PRODUCTION_NIGHTS`` was read from production on 2026-09-22 and
each one is reproducible:

* ``old_rule_peak`` is what ``_temperature_peaks``/``_indoor_peaks`` computed
  before this batch — every reading in the period, anything from 18:00 local
  attributed to the next morning, keep the maximum. The two stored weekly-review
  packets corroborate the column exactly: 7-13 Sep gave ``avgIndoorPeakC 20.9``
  with ``disruptionNights 7``, and 14-20 Sep gave ``20.5`` with ``5``. Those are
  the figures Mark disputed on 13 Sep and twice on 21 Sep, and he was right.
* ``sleep_window_peak`` is the maximum between ``sleep_start_utc`` and
  ``sleep_end_utc`` — the hours he was actually asleep, which is what the
  morning brief has always shown and what has never been disputed.

The gap between the two columns is the bug: roughly 2 degrees every night for a
fortnight, enough to turn a bedroom that never reached 20 degrees into "5 of 7
nights showed thermal disruption".
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from src.models.coaching import Sleep, TemperatureReading
from src.services.night_thermal import night_indoor_peaks
from src.services.reviews import (
    THERMAL_DISRUPTION_C,
    ReviewThermalNight,
    compute_review_rollup,
)

LONDON = ZoneInfo("Europe/London")


@dataclass(frozen=True)
class ProductionNight:
    wake_date: date
    old_rule_peak: float
    sleep_window_peak: float
    sleep_start_local: time
    sleep_end_local: time


# Read from production 2026-09-22. See the module docstring.
PRODUCTION_NIGHTS: tuple[ProductionNight, ...] = (
    ProductionNight(date(2026, 9, 7), 21.41, 18.97, time(22, 43), time(6, 15)),
    ProductionNight(date(2026, 9, 8), 20.00, 18.38, time(22, 27), time(6, 22)),
    ProductionNight(date(2026, 9, 9), 20.69, 17.87, time(22, 29), time(6, 25)),
    ProductionNight(date(2026, 9, 10), 20.92, 19.02, time(22, 6), time(6, 16)),
    ProductionNight(date(2026, 9, 11), 21.20, 19.20, time(22, 22), time(6, 14)),
    ProductionNight(date(2026, 9, 12), 21.17, 18.87, time(22, 22), time(6, 13)),
    ProductionNight(date(2026, 9, 13), 21.25, 18.94, time(22, 20), time(6, 51)),
    ProductionNight(date(2026, 9, 14), 21.23, 19.71, time(22, 31), time(5, 48)),
    ProductionNight(date(2026, 9, 15), 21.30, 19.41, time(22, 13), time(6, 20)),
    ProductionNight(date(2026, 9, 16), 20.41, 18.41, time(22, 43), time(6, 26)),
    ProductionNight(date(2026, 9, 17), 20.33, 18.97, time(22, 19), time(6, 33)),
    ProductionNight(date(2026, 9, 18), 19.61, 18.10, time(22, 31), time(6, 11)),
    ProductionNight(date(2026, 9, 19), 19.64, 19.02, time(22, 54), time(6, 11)),
    ProductionNight(date(2026, 9, 20), 21.17, 18.25, time(22, 27), time(6, 32)),
    # The one genuinely warm night in the fortnight, and the reason the threshold
    # must not be tuned away: it is also one of the two genuine Red mornings.
    ProductionNight(date(2026, 9, 21), 21.12, 20.25, time(22, 35), time(6, 5)),
    ProductionNight(date(2026, 9, 22), 22.33, 19.30, time(22, 27), time(6, 32)),
)


def _utc(local: datetime) -> datetime:
    """Local wall-clock to the UTC-naive form the ``*_utc`` columns hold."""
    return local.replace(tzinfo=LONDON).astimezone(UTC).replace(tzinfo=None)


def _reading(user_id: uuid.UUID, local: datetime, celsius: float) -> TemperatureReading:
    return TemperatureReading(user_id=user_id, captured_at_utc=_utc(local), temperature_c=celsius)


def _sleep(user_id: uuid.UUID, night: ProductionNight) -> Sleep:
    wake = night.wake_date
    return Sleep(
        user_id=user_id,
        calendar_date=wake,
        sleep_start_utc=_utc(datetime.combine(wake - timedelta(days=1), night.sleep_start_local)),
        sleep_end_utc=_utc(datetime.combine(wake, night.sleep_end_local)),
    )


def _production_fixture(
    user_id: uuid.UUID, nights: tuple[ProductionNight, ...]
) -> tuple[list[TemperatureReading], list[Sleep]]:
    """Two readings a night: the daytime peak, and the real asleep peak.

    The daytime reading is placed at 14:07 on the wake date, which is exactly
    where the old rule put it — before 18:00, so attributed to that same morning.
    """
    rows: list[TemperatureReading] = []
    sleeps: list[Sleep] = []
    for night in nights:
        rows.append(
            _reading(
                user_id,
                datetime.combine(night.wake_date, time(14, 7)),
                night.old_rule_peak,
            )
        )
        rows.append(
            _reading(
                user_id,
                datetime.combine(night.wake_date, time(2, 30)),
                night.sleep_window_peak,
            )
        )
        sleeps.append(_sleep(user_id, night))
    return rows, sleeps


def _peaks_for(nights: tuple[ProductionNight, ...]) -> dict[date, float]:
    user_id = uuid.uuid4()
    rows, sleeps = _production_fixture(user_id, nights)
    result = night_indoor_peaks(
        rows,
        sleeps,
        start=nights[0].wake_date,
        end=nights[-1].wake_date,
        timezone_name="Europe/London",
    )
    return {day: peak.peak_c for day, peak in result.items()}


def _window(start: date, end: date) -> tuple[ProductionNight, ...]:
    return tuple(n for n in PRODUCTION_NIGHTS if start <= n.wake_date <= end)


def _disruption_nights(peaks: dict[date, float]) -> int:
    return sum(1 for value in peaks.values() if value >= THERMAL_DISRUPTION_C)


def test_an_afternoon_reading_is_not_the_bedroom() -> None:
    """The defect in one fixture: 21.4 at 14:07, 18.1 asleep — report 18.1."""
    user_id = uuid.uuid4()
    wake = date(2026, 9, 18)
    rows = [
        _reading(user_id, datetime.combine(wake, time(14, 7)), 21.4),
        _reading(user_id, datetime.combine(wake, time(2, 30)), 18.1),
    ]
    sleeps = [
        Sleep(
            user_id=user_id,
            calendar_date=wake,
            sleep_start_utc=_utc(datetime.combine(wake - timedelta(days=1), time(22, 31))),
            sleep_end_utc=_utc(datetime.combine(wake, time(6, 11))),
        )
    ]
    peaks = night_indoor_peaks(rows, sleeps, start=wake, end=wake, timezone_name="Europe/London")
    assert peaks[wake].peak_c == 18.1
    assert peaks[wake].window_source == "sleep"
    assert _disruption_nights({wake: peaks[wake].peak_c}) == 0


def test_first_contested_week_reports_zero_not_seven() -> None:
    """7-13 Sep. The stored packet said 7 of 7 at an average of 20.9."""
    nights = _window(date(2026, 9, 7), date(2026, 9, 13))
    assert len(nights) == 7
    old_rule_disruptions = sum(1 for n in nights if n.old_rule_peak >= THERMAL_DISRUPTION_C)
    assert old_rule_disruptions == 7, "fixture must reproduce the disputed figure"

    peaks = _peaks_for(nights)
    assert _disruption_nights(peaks) == 0
    assert max(peaks.values()) == 19.20
    assert min(peaks.values()) == 17.87


def test_second_contested_week_reports_zero_not_five() -> None:
    """14-20 Sep. The stored packet said 5 of 7 at an average of 20.5."""
    nights = _window(date(2026, 9, 14), date(2026, 9, 20))
    assert len(nights) == 7
    old_rule_disruptions = sum(1 for n in nights if n.old_rule_peak >= THERMAL_DISRUPTION_C)
    assert old_rule_disruptions == 5, "fixture must reproduce the disputed figure"

    peaks = _peaks_for(nights)
    assert _disruption_nights(peaks) == 0
    assert max(peaks.values()) == 19.71


def test_the_one_genuinely_warm_night_still_counts() -> None:
    """15-21 Sep reports exactly one disruption night — 21 Sep, at 20.25.

    Without this the suite cannot tell a working detector from a dead one: every
    other assertion here is that the count went to zero.
    """
    nights = _window(date(2026, 9, 15), date(2026, 9, 21))
    assert len(nights) == 7
    peaks = _peaks_for(nights)
    assert _disruption_nights(peaks) == 1
    assert peaks[date(2026, 9, 21)] == 20.25
    assert peaks[date(2026, 9, 21)] >= THERMAL_DISRUPTION_C


def test_a_night_without_a_sleep_row_falls_back_to_the_clock() -> None:
    """No sleep row: the 21:30-09:00 window, and the source says so.

    Verified at /batch-start that this path has never run in production — of 90
    nights carrying temperature data since 1 June, zero lack a sleep row — so it
    is defensive, and only a synthetic fixture can cover it.
    """
    user_id = uuid.uuid4()
    wake = date(2026, 9, 18)
    rows = [
        _reading(user_id, datetime.combine(wake, time(14, 7)), 21.4),
        _reading(user_id, datetime.combine(wake - timedelta(days=1), time(20, 45)), 20.9),
        _reading(user_id, datetime.combine(wake - timedelta(days=1), time(22, 0)), 18.6),
        _reading(user_id, datetime.combine(wake, time(3, 0)), 18.1),
        _reading(user_id, datetime.combine(wake, time(10, 30)), 21.8),
    ]
    peaks = night_indoor_peaks(rows, [], start=wake, end=wake, timezone_name="Europe/London")
    assert peaks[wake].window_source == "night_fallback"
    # 20:45 is before the window opens and 10:30 is after it closes; neither is
    # his night, and the old rule would have taken both.
    assert peaks[wake].peak_c == 18.6
    assert peaks[wake].sample_count == 2


def test_a_long_sleep_row_cannot_drag_daytime_back_in() -> None:
    """The window is the intersection, not the sleep row alone."""
    user_id = uuid.uuid4()
    wake = date(2026, 9, 18)
    rows = [
        _reading(user_id, datetime.combine(wake - timedelta(days=1), time(19, 0)), 22.5),
        _reading(user_id, datetime.combine(wake - timedelta(days=1), time(23, 0)), 18.2),
        _reading(user_id, datetime.combine(wake, time(11, 0)), 23.1),
    ]
    sleeps = [
        Sleep(
            user_id=user_id,
            calendar_date=wake,
            # Deliberately absurd: 19:00 to 11:00, wider than the clock window.
            sleep_start_utc=_utc(datetime.combine(wake - timedelta(days=1), time(19, 0))),
            sleep_end_utc=_utc(datetime.combine(wake, time(11, 0))),
        )
    ]
    peaks = night_indoor_peaks(rows, sleeps, start=wake, end=wake, timezone_name="Europe/London")
    assert peaks[wake].peak_c == 18.2
    assert peaks[wake].window_source == "sleep"


def test_an_unmeasured_night_is_absent_rather_than_cold() -> None:
    """A night with no readings must not enter the rollup as a zero or a None."""
    user_id = uuid.uuid4()
    measured = date(2026, 9, 18)
    rows = [_reading(user_id, datetime.combine(measured, time(2, 30)), 18.1)]
    sleeps = [
        Sleep(
            user_id=user_id,
            calendar_date=measured,
            sleep_start_utc=_utc(datetime.combine(measured - timedelta(days=1), time(22, 31))),
            sleep_end_utc=_utc(datetime.combine(measured, time(6, 11))),
        )
    ]
    peaks = night_indoor_peaks(
        rows,
        sleeps,
        start=measured,
        end=measured + timedelta(days=2),
        timezone_name="Europe/London",
    )
    assert set(peaks) == {measured}


def test_rollup_labels_the_outdoor_low_and_counts_its_window_sources() -> None:
    """268.2 — the packet key says outdoor, and fallback nights are visible."""
    nights = [
        ReviewThermalNight(
            day=date(2026, 9, 18),
            indoor_peak_c=18.1,
            outdoor_overnight_low_c=12.6,
            indoor_window_source="sleep",
        ),
        ReviewThermalNight(
            day=date(2026, 9, 19),
            indoor_peak_c=19.0,
            outdoor_overnight_low_c=12.6,
            indoor_window_source="night_fallback",
        ),
    ]
    rollup = compute_review_rollup(
        [],
        [],
        [],
        nights,
        period="weekly",
        period_start=date(2026, 9, 18),
        period_end=date(2026, 9, 19),
        planned_count=0,
    )
    assert rollup.thermal.avg_outdoor_overnight_low_c == 12.6
    assert rollup.thermal.disruption_nights == 0
    assert rollup.thermal.nights_from_sleep_window == 1
    assert rollup.thermal.nights_from_clock_fallback == 1
