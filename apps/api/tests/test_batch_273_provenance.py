"""Batch 273 — every covered figure shows its working, and CI says so.

The contract this file enforces is the one 273.4 asks for: **a derived figure
without provenance fails a test**, so the panel cannot silently go stale as new
figures are added. Each covered producer is driven with real shapes and its
provenance read back.

The 7–13 September bedroom-peak argument is the worked example throughout: a
21.4 °C "overnight" reading that was an afternoon sample. The test below builds
exactly that contamination and asserts the provenance makes it visible without any
prior knowledge of the bug.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Any

import pytest

from src.models.coaching import Sleep, TemperatureReading
from src.services.coach_sections import thermal_review
from src.services.provenance import (
    DEFERRED_FIGURES,
    FIGURE_BEDROOM_PEAK,
    FIGURE_HRV_ACUTE_FLOOR,
    FIGURE_INTERVAL_GRADING,
    FIGURE_REVIEW_AVG_PEAK,
    FIGURE_REVIEW_DISRUPTION_NIGHTS,
    PROVENANCED_FIGURES,
    Provenance,
    covered_figures,
)

REQUIRED_KEYS = {"figure", "label", "value", "units", "rule", "window", "sources", "threshold"}


def _reading(when: datetime, celsius: float) -> TemperatureReading:
    return TemperatureReading(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        captured_at_utc=when,
        temperature_c=celsius,
        source="hive",
        raw_payload={},
    )


def _sleep(start: datetime, end: datetime) -> Sleep:
    return Sleep(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        calendar_date=end.date(),
        sleep_start_utc=start,
        sleep_end_utc=end,
        raw_payload={},
    )


def _assert_well_formed(entry: dict[str, Any]) -> None:
    assert set(entry) == REQUIRED_KEYS, f"{entry.get('figure')} has the wrong shape"
    assert entry["figure"] in PROVENANCED_FIGURES
    assert entry["label"] and not entry["label"][0].isupper() or entry["label"][0].isupper()
    assert isinstance(entry["rule"], str) and len(entry["rule"]) > 20, (
        f"{entry['figure']}'s rule must say what was done, not name it"
    )
    assert isinstance(entry["sources"], dict) and entry["sources"], (
        f"{entry['figure']} must say what it read"
    )


# -- the contract ------------------------------------------------------------


def test_every_covered_figure_is_produced_with_its_working() -> None:
    """The contract test. A figure listed as covered that no producer emits — or a
    producer that stops emitting one — fails here rather than going quiet on a
    panel nobody is checking."""
    produced: set[str] = set()
    produced |= covered_figures(_thermal_packet()["provenance"])
    produced |= covered_figures(_review_thermal_provenance())
    produced |= covered_figures(_hrv_provenance())
    produced |= covered_figures(_grading_provenance())

    missing = PROVENANCED_FIGURES - produced
    assert not missing, f"covered figures with no provenance produced: {sorted(missing)}"

    unexpected = produced - PROVENANCED_FIGURES
    assert not unexpected, (
        f"a producer emitted provenance for an unregistered figure: {sorted(unexpected)}. "
        "Add it to PROVENANCED_FIGURES or to DEFERRED_FIGURES with a reason."
    )


def test_a_covered_figure_and_a_deferred_one_are_never_the_same_figure() -> None:
    assert not PROVENANCED_FIGURES & set(DEFERRED_FIGURES)


def test_every_deferral_gives_a_reason_rather_than_a_todo() -> None:
    """273.3 asks for the deferrals to be recorded. A bare key would record nothing."""
    for figure, reason in DEFERRED_FIGURES.items():
        assert len(reason) > 60, f"{figure}'s deferral does not say why"


def test_provenance_never_reads_the_prose() -> None:
    """273.1's governing constraint: the derivation is packet-side, so it survives a
    prompt-version change because it never depended on one. A `Provenance` carries
    no reference to any generated text and nothing here parses markdown."""
    entry = Provenance(
        figure=FIGURE_BEDROOM_PEAK,
        label="x",
        value=1,
        rule="a rule long enough to describe what was actually done here",
        sources={"table": "t"},
    ).to_packet()
    assert set(entry) == REQUIRED_KEYS
    assert "markdown" not in entry
    assert "promptVersion" not in entry


# -- the worked example: 7-13 September ---------------------------------------


def _thermal_packet(*, contaminated: bool = False) -> dict[str, Any]:
    night_start = datetime(2026, 9, 8, 22, 0)
    night_end = datetime(2026, 9, 9, 6, 0)
    rows = [_reading(night_start + timedelta(minutes=30 * i), 18.5 + 0.1 * i) for i in range(16)]
    if contaminated:
        # The afternoon sample that started the argument.
        rows.insert(0, _reading(datetime(2026, 9, 8, 14, 7), 21.4))
    sleep = None if contaminated else _sleep(night_start, night_end)
    if contaminated:
        return thermal_review(rows, None, {}, sleep=None)
    return thermal_review(rows, None, {}, sleep=sleep)


def test_the_bedroom_peak_says_which_window_it_used_and_how_many_rows() -> None:
    entry = _thermal_packet()["provenance"][0]
    _assert_well_formed(entry)
    assert entry["figure"] == FIGURE_BEDROOM_PEAK
    assert entry["window"]["kind"] == "sleep"
    assert entry["window"]["startUtc"] == "2026-09-08T22:00:00"
    assert entry["sources"]["rowsInWindow"] == 16
    assert entry["threshold"]["comparedAgainst"] == 20.0


def test_the_afternoon_contamination_is_visible_without_knowing_about_the_bug() -> None:
    """The 7-13 September case. With no sleep times the window is a clock fallback,
    the 14:07 sample is inside it, and the panel says so in as many words."""
    packet = _thermal_packet(contaminated=True)
    entry = packet["provenance"][0]
    _assert_well_formed(entry)
    assert packet["indoorPeakC"] == 21.4
    assert entry["window"]["kind"] == "night_fallback"
    assert "clock" in entry["window"]["label"]
    assert "awake" in entry["rule"]
    assert entry["sources"]["firstReadingUtc"] == "2026-09-08T14:07:00"


def test_a_measured_night_does_not_claim_a_fallback_window() -> None:
    entry = _thermal_packet()["provenance"][0]
    assert "clock" not in (entry["window"]["label"] or "")
    assert entry["window"]["label"] == "the night he actually slept"


# -- the other three producers ------------------------------------------------


def _review_thermal_provenance() -> list[dict[str, Any]]:
    from src.services.reviews import ReviewThermalNight, compute_review_rollup

    thermal = [
        ReviewThermalNight(
            day=date(2026, 9, 7) + timedelta(days=i),
            indoor_peak_c=21.4 if i < 2 else 18.9,
            outdoor_overnight_low_c=11.0,
            indoor_window_source="night_fallback" if i < 2 else "sleep",
        )
        for i in range(7)
    ]
    rollup = compute_review_rollup(
        [],
        [],
        [],
        thermal,
        period="week",
        period_start=date(2026, 9, 7),
        period_end=date(2026, 9, 13),
        planned_count=0,
    )
    return rollup.thermal.provenance


def test_the_review_thermal_figures_say_how_many_nights_were_a_fallback() -> None:
    entries = _review_thermal_provenance()
    by_figure = {e["figure"]: e for e in entries}
    for entry in entries:
        _assert_well_formed(entry)
    assert set(by_figure) == {FIGURE_REVIEW_AVG_PEAK, FIGURE_REVIEW_DISRUPTION_NIGHTS}
    disruption = by_figure[FIGURE_REVIEW_DISRUPTION_NIGHTS]
    assert disruption["value"] == 2
    assert disruption["sources"]["nightsFromClockFallback"] == 2
    assert disruption["sources"]["nightsFromSleepWindow"] == 5
    assert disruption["threshold"]["comparedAgainst"] is not None
    assert "cannot count either way" in disruption["rule"]


def _hrv_provenance() -> list[dict[str, Any]]:
    from src.models.coaching import DailyMetric
    from src.services.morning_verdict import _hrv_rail

    subject = date(2026, 9, 22)
    today = DailyMetric(
        user_id=uuid.uuid4(),
        calendar_date=subject,
        phase="morning",
        hrv_last_night_avg_ms=36,
        raw_payload={},
    )
    history = [
        DailyMetric(
            user_id=uuid.uuid4(),
            calendar_date=subject - timedelta(days=offset),
            phase="morning",
            hrv_last_night_avg_ms=value,
            raw_payload={},
        )
        # ACUTE_BASELINE_MIN_SAMPLES is 21, over an 84-day window.
        for offset, value in enumerate(
            [47, 44, 51, 45, 49, 42, 53, 46, 48, 44, 50, 47, 45, 49] * 2, start=1
        )
    ]
    return _hrv_rail(today, history)["provenance"]


def test_the_hrv_floor_names_its_rule_its_window_and_its_nights() -> None:
    entries = _hrv_provenance()
    entry = entries[0]
    _assert_well_formed(entry)
    assert entry["figure"] == FIGURE_HRV_ACUTE_FLOOR
    assert entry["units"] == "ms"
    assert "standard deviations" in entry["rule"]
    assert "not Garmin's" in entry["rule"]
    assert entry["sources"]["nightsUsed"] == 28
    assert entry["sources"]["medianMs"] is not None
    assert entry["window"]["kind"] == "rolling_days"


def _grading_provenance() -> list[dict[str, Any]]:
    """Two graded work intervals, one on target and one under — the 8 September
    shape, where a held average and a peak disagree."""
    from src.services.ride_intervals import summarize_execution

    def work(label: str, adherence: str, pct_ftp: int) -> dict[str, Any]:
        return {
            "role": "work",
            "label": label,
            "adherence": adherence,
            "durationSec": 150,
            "targetPctFtpLow": 114,
            "targetPctFtpHigh": 124,
            "pctFtp": pct_ftp,
            "boundarySource": "planned_durations",
            "clockSource": "timer",
            "pausedSec": 0,
        }

    intervals = [
        work("VO2 1", "on", 119),
        # The 8 September shape: graded under on its held average while its peak
        # was well above target.
        work("VO2 2", "under", 104) | {"maxPowerWatts": 352, "peakPctFtp": 126},
        {"role": "recovery", "label": "recover", "boundarySource": "planned_durations"},
    ]
    return summarize_execution(intervals, whole_ride_avg_power_watts=176)["provenance"]


def test_the_grading_basis_says_which_statistic_it_used() -> None:
    """Mark's 8 September dispute: five "under" calls he checked against Garmin and
    found above 350 W at peak. Both readings were right; the basis differed."""
    entries = _grading_provenance()
    entry = entries[0]
    _assert_well_formed(entry)
    assert entry["figure"] == FIGURE_INTERVAL_GRADING
    assert "average power it held" in entry["rule"]
    assert "not its peak" in entry["rule"]
    assert "withheld" in entry["rule"]
    assert entry["sources"]["workIntervals"] >= 1


@pytest.mark.parametrize("figure", sorted(PROVENANCED_FIGURES))
def test_each_covered_figure_key_is_addressable_in_the_packet(figure: str) -> None:
    """A figure key is a path a reader can follow, not an opaque id."""
    assert "." in figure, f"{figure} should read as section.figureName"
    assert figure == figure.strip()
