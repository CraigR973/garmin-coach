"""Batch 354: the notices give their windows as "10 Jun to 1 Sep".

The oxygen notices and the off-the-bike HRV notice printed their baseline windows as
ISO dates ("from 2026-06-10 to 2026-09-01"). Craig chose "10 Jun to 1 Sep" on 27 Oct
(Decision #442). The packet keeps its ISO fields for the brief and the coach.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from src.services.morning_verdict import _window_words
from tests.test_morning_verdict import TODAY, _complete_verdict, _metric, _sleep

ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _notices(verdict: dict) -> list[str]:
    return [item["message"] for item in verdict["acutePhysiology"]["escalations"]]


def _hrv_illness_grade() -> dict:
    values = [43] * 10 + [47] + [51] * 10
    history = [
        _metric(last_night_hrv=value, day=TODAY - timedelta(days=len(values) - index))
        for index, value in enumerate(values)
    ]
    return _complete_verdict(daily_metric=_metric(last_night_hrv=37), recent_daily_metrics=history)


def test_window_words_give_day_and_month() -> None:
    assert _window_words(date(2026, 6, 10), date(2026, 9, 1)) == " from 10 Jun to 1 Sep"
    # No year, even across New Year: every window ends within days of its morning.
    assert _window_words(date(2026, 12, 10), date(2027, 3, 1)) == " from 10 Dec to 1 Mar"
    assert _window_words(None, date(2026, 9, 1)) == ""
    assert _window_words(date(2026, 6, 10), None) == ""


def test_no_notice_prints_an_iso_date() -> None:
    low_average = _complete_verdict(sleep=_sleep(average_spo2=89, lowest_spo2=87, respiration=17))
    low_nights = _complete_verdict(
        sleep=_sleep(average_spo2=96, lowest_spo2=86, respiration=13),
        recent_sleeps=[
            _sleep(day=TODAY - timedelta(days=1), average_spo2=96, lowest_spo2=87, respiration=13)
        ],
    )
    for verdict in (low_average, low_nights, _hrv_illness_grade()):
        notices = _notices(verdict)
        assert notices
        for notice in notices:
            assert not ISO_DATE.search(notice), notice
            assert " from " in notice and " to " in notice


def test_the_off_the_bike_hrv_notice_reads_as_signed_off_with_its_dates_in_words() -> None:
    [notice] = _notices(_hrv_illness_grade())
    assert notice == (
        "Your overnight HRV is 37 ms this morning against a usual 47 ms from 12 Aug to "
        "1 Sep — a drop that size in a single night is unusual for you. It usually means "
        "one of: an infection starting, a heavy drink, a badly broken night, or real "
        "stress carried into sleep. Training hard through it tends to deepen it. Take "
        "today off the bike, and if you feel unwell alongside it, see your GP rather than "
        "just resting."
    )


def test_the_packet_keeps_its_iso_window_dates() -> None:
    oxygen = _complete_verdict(sleep=_sleep(average_spo2=89, lowest_spo2=87, respiration=17))[
        "acutePhysiology"
    ]["oxygenRespiration"]
    assert oxygen["spo2BaselineWindowStartDate"] == "2026-06-10"
    assert oxygen["spo2BaselineWindowEndDate"] == "2026-09-01"
    assert oxygen["respirationBaselineWindowStartDate"] == "2026-06-10"
    assert oxygen["respirationBaselineWindowEndDate"] == "2026-09-01"
    hrv = _hrv_illness_grade()["acutePhysiology"]["overnightHrv"]
    assert hrv["baselineWindowStartDate"] == "2026-08-12"
    assert hrv["baselineWindowEndDate"] == "2026-09-01"
