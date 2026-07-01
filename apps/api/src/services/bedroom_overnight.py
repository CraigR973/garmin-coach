"""Overnight bedroom chart — pure night-windowing, hypnogram + summary helpers (Batch 31).

The read API (``routers/bedroom.py``) is a thin DB shell over these pure
functions: it queries ``temperature_readings`` + ``fan_state_readings`` + the
night's ``sleep`` row for one overnight window and serialises them for the
``/bedroom`` chart. Keeping the windowing, the hypnogram extraction, and the
Home-glance summary here makes them exhaustively unit-testable without a DB.

The chart window and threshold lines reuse the fan-control constants so the chart
and the autopilot can never disagree about "what counts as overnight" or where the
sleep-disruption lines sit (Batch 9 / Batch 27).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from src.services.fan_control import INTERVAL_MIN, WINDDOWN_END, WINDOW_START

# Reference lines on the chart — the Batch 9 sleep-disruption thresholds.
# 19.5 °C is the fan-on warning line (``fan_control.ON_THRESHOLD_C``); 20.0 °C is
# the critical line (``nudge_alerts.evaluate_thermal_alert``).
THRESHOLD_ON_C = 19.5
THRESHOLD_CRITICAL_C = 20.0
RED_CRITICAL_MINUTES = 60

# Garmin sleep-levels (hypnogram) ``activityLevel`` → stage label.
SLEEP_STAGE_BY_LEVEL: dict[int, str] = {0: "deep", 1: "light", 2: "rem", 3: "awake"}
RoomVerdict = Literal["green", "amber", "red"]


@dataclass(frozen=True)
class OvernightSummary:
    """The Home-glance roll-up for one night (range, run-hours, peak speed)."""

    min_temp_c: float | None
    max_temp_c: float | None
    fan_ran_minutes: int
    peak_speed: int | None
    warning_minutes: int
    critical_minutes: int
    room_verdict: RoomVerdict


def night_window(night: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """UTC-naive ``(start, end)`` for the overnight window that *starts* on ``night``.

    The window is ``WINDOW_START`` (21:30) on ``night`` → ``WINDDOWN_END`` (09:00)
    the next morning, in the profile's local zone, converted to UTC for querying
    the ``*_utc`` columns.
    """
    start_local = datetime.combine(night, WINDOW_START, tzinfo=tz)
    end_local = datetime.combine(night + timedelta(days=1), WINDDOWN_END, tzinfo=tz)
    return (_to_utc_naive(start_local), _to_utc_naive(end_local))


def default_night(now_local: datetime) -> date:
    """The most recent *completed* night (its window has fully ended)."""
    today = now_local.date()
    if now_local.time() >= WINDDOWN_END:
        # Past this morning's wind-down → last night (started yesterday) is done.
        return today - timedelta(days=1)
    # Still inside last night's window → the last completed one started two days ago.
    return today - timedelta(days=2)


def night_for_local(moment_local: datetime) -> date | None:
    """The night a local timestamp belongs to, or ``None`` if it is daytime (idle)."""
    clock = moment_local.time()
    if clock >= WINDOW_START:  # 21:30 → midnight: tonight
        return moment_local.date()
    if clock < WINDDOWN_END:  # midnight → 09:00: last night
        return moment_local.date() - timedelta(days=1)
    return None  # 09:00 → 21:30: daytime, not charted


def recent_nights(local_timestamps: Iterable[datetime], *, limit: int = 14) -> list[date]:
    """Distinct night dates (newest first) covered by the given local timestamps."""
    nights = {
        night for moment in local_timestamps if (night := night_for_local(moment)) is not None
    }
    return sorted(nights, reverse=True)[:limit]


def sleep_calendar_date(night: date) -> date:
    """Garmin keys a night's sleep row by the *wake* morning, i.e. ``night + 1``."""
    return night + timedelta(days=1)


def extract_hypnogram(raw_payload: Mapping[str, Any] | None) -> list[dict[str, str]]:
    """Per-interval sleep stages from ``sleep.raw_payload['sleepLevels']``.

    Returns ``[{start, end, stage}]`` with ISO-8601 ``Z`` times, skipping any
    malformed entry. Empty when no hypnogram is present (older rows / no payload),
    which the chart degrades to a plain sleep-window band.
    """
    if not isinstance(raw_payload, Mapping):
        return []
    levels = raw_payload.get("sleepLevels")
    if not isinstance(levels, list):
        return []
    spans: list[dict[str, str]] = []
    for entry in levels:
        if not isinstance(entry, Mapping):
            continue
        start = _parse_gmt(entry.get("startGMT"))
        end = _parse_gmt(entry.get("endGMT"))
        if start is None or end is None:
            continue
        level = entry.get("activityLevel")
        stage = SLEEP_STAGE_BY_LEVEL.get(int(level)) if isinstance(level, (int, float)) else None
        spans.append({"start": iso_z(start), "end": iso_z(end), "stage": stage or "unknown"})
    return spans


def summarize_overnight(
    temperatures_c: Sequence[float | None],
    fan_states: Sequence[tuple[bool | None, int | None]],
    *,
    interval_min: int = INTERVAL_MIN,
) -> OvernightSummary:
    """Roll the night's series up for the one-line Home glance.

    ``fan_ran_minutes`` counts the on-ticks × the loop interval; ``peak_speed`` is
    the highest speed while running. Temperature range is over the room curve, and
    the verdict reuses the existing warning/critical chart thresholds.
    """
    temps = [t for t in temperatures_c if t is not None]
    on_ticks = [(on, speed) for on, speed in fan_states if on]
    speeds = [speed for _on, speed in on_ticks if speed is not None]
    warning_minutes = sum(1 for t in temps if t >= THRESHOLD_ON_C) * interval_min
    critical_minutes = sum(1 for t in temps if t >= THRESHOLD_CRITICAL_C) * interval_min
    return OvernightSummary(
        min_temp_c=round(min(temps), 1) if temps else None,
        max_temp_c=round(max(temps), 1) if temps else None,
        fan_ran_minutes=len(on_ticks) * interval_min,
        peak_speed=max(speeds) if speeds else None,
        warning_minutes=warning_minutes,
        critical_minutes=critical_minutes,
        room_verdict=room_verdict(warning_minutes, critical_minutes),
    )


def room_verdict(warning_minutes: int, critical_minutes: int) -> RoomVerdict:
    """Classify the night's room impact from threshold minutes."""
    if warning_minutes <= 0:
        return "green"
    if critical_minutes >= RED_CRITICAL_MINUTES:
        return "red"
    return "amber"


def iso_z(naive_utc: datetime) -> str:
    """Serialise a UTC-naive datetime as an ISO-8601 string with a ``Z`` suffix."""
    return naive_utc.replace(microsecond=0).isoformat() + "Z"


def _to_utc_naive(aware: datetime) -> datetime:
    return aware.astimezone(UTC).replace(tzinfo=None)


def _parse_gmt(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.strip())
    except ValueError:
        return None
