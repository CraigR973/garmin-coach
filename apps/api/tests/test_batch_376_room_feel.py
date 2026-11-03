"""Batch 376 — the Home badge and the Bedroom chart on Batch 366's lines.

After 366 the pushes judged the room warm from 24 °C and cold below 18 °C, but the badge
still read Red after 60 minutes above 20 °C and the chart labelled 20 °C "critical".
"""

from __future__ import annotations

from src.routers.bedroom import OvernightSummaryOut, OvernightThresholds
from src.services.bedroom_overnight import room_feel, summarize_overnight
from src.services.fan_control import INTERVAL_MIN


def _night(*temps: float) -> list[float | None]:
    return list(temps)


def test_an_october_night_that_was_red_is_comfortable() -> None:
    # 2 h at 20.1–20.9 °C: the old badge said Red; it is inside 18–24 °C.
    temps = _night(*([20.5] * (120 // INTERVAL_MIN)), *([19.4] * 10))
    summary = summarize_overnight(temps, [])
    assert summary.room_verdict == "red"
    assert summary.room_feel == "comfortable"
    assert (summary.warm_minutes, summary.cold_minutes) == (0, 0)


def test_an_hour_past_a_line_is_warm_or_cold() -> None:
    hour = 60 // INTERVAL_MIN
    assert summarize_overnight(_night(*([24.2] * hour)), []).room_feel == "warm"
    assert summarize_overnight(_night(*([17.6] * hour)), []).room_feel == "cold"
    assert summarize_overnight(_night(*([17.6] * (hour - 1)), 19.0), []).room_feel == (
        "comfortable"
    )


def test_the_longer_side_wins_a_night_with_both() -> None:
    assert room_feel(warm_minutes=90, cold_minutes=60) == "warm"
    assert room_feel(warm_minutes=60, cold_minutes=75) == "cold"


def test_the_api_carries_the_new_lines_and_keeps_the_old_fields() -> None:
    assert set(OvernightThresholds.model_fields) == {"onC", "criticalC", "coldC", "warmC"}
    assert {"roomVerdict", "roomFeel", "warmMinutes", "coldMinutes"} <= set(
        OvernightSummaryOut.model_fields
    )
