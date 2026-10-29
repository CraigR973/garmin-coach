"""Batch 317 — Home shows why, in one set of numbers.

Measured on 6 Oct and re-verified on 28 Oct: the engine writes a one-line reason with his
numbers (``graded.summary``) that no screen shows; his "usual" HRV was three numbers (the
acute rail's median, the engine's mean, and the median of Garmin's 7-day averages in the
metrics table); and a fair night that readiness confirms read "clearly off: a fair night's
sleep … (your readiness agrees)".

* **The reason reaches Home:** the daily loop sends the stored line (``verdictSummary``),
  and nothing for a morning the ladder graded.
* **One HRV normal (Decision #450):** the mean of his nightly HRV over the 84 nights
  before the morning, the number the 7-day reading is judged against. The acute rail
  publishes it as ``usualMs`` beside its median, which still sets the floor; every
  Mark-facing HRV "usual" quotes it, rounded to a whole ms; the metrics table's HRV row
  is centred on it; the brief is told it is the only one.
* **The confirmed fair night** has its own words, never "fair" under "clearly off".
* **No colour or action changes:** only words and one table centre move.
"""

from __future__ import annotations

import itertools
import uuid
from datetime import UTC, date, datetime, timedelta
from statistics import median
from typing import Any

import pytest

from src.models.coaching import DAILY_METRIC_PHASE_MORNING, Analysis, DailyMetric
from src.services import morning_analysis
from src.services.daily_loop_envelope import _serialize_analysis
from src.services.morning_verdict import _hrv_rail
from src.services.verdict_grading import (
    DOMAIN_AUTONOMIC,
    DOMAIN_LOAD,
    DOMAIN_SLEEP,
    DOMAIN_SUBJECTIVE,
    DomainRating,
    SignalReading,
    _domain_phrase,
    _hrv_overnight,
    _hrv_week_on,
    build_grading_inputs,
    grade,
    mark_facing_phrase,
    mark_facing_summary,
)
from tests.test_batch_295_verdict_grading import _acute, _inputs

TODAY = date(2026, 10, 7)

#: A skewed run of nights, so his mean and median differ as they do in his real data
#: (46.3 against 47 on 5 Oct): one low night in five pulls the mean under the median.
NIGHTS = (40, 47, 47, 48, 50)


def _row(day: date, hrv: int | None) -> DailyMetric:
    return DailyMetric(
        user_id=uuid.uuid4(),
        calendar_date=day,
        phase=DAILY_METRIC_PHASE_MORNING,
        hrv_last_night_avg_ms=hrv,
        raw_payload={},
    )


def _history() -> list[DailyMetric]:
    return [_row(TODAY - timedelta(days=offset), NIGHTS[offset % 5]) for offset in range(1, 85)]


def _values() -> list[int]:
    return [NIGHTS[offset % 5] for offset in range(1, 85)]


def _mean() -> float:
    values = _values()
    return sum(values) / len(values)


# -- one normal ---------------------------------------------------------------------------


def test_the_rail_publishes_his_usual_as_the_mean_of_the_nights_its_floor_uses() -> None:
    rail = _hrv_rail(_row(TODAY, 38), _history())

    assert rail["baselineMedianMs"] == median(_values()) == 47
    assert rail["usualMs"] == round(_mean(), 2) == 46.48
    # The floor is still the median's, so no morning changes colour.
    assert rail["acuteFloorMs"] == round(47 - 1.5 * rail["baselineStddevMs"], 2)


def test_the_rails_notice_quotes_his_usual_not_the_median() -> None:
    rail = _hrv_rail(_row(TODAY, 38), _history())

    assert rail["triggered"] is True
    assert "Your overnight HRV is 38 ms this morning against a usual 46 ms" in rail["escalation"]
    assert "usual 47" not in rail["escalation"]


def test_his_usual_is_the_number_the_7_day_reading_judges_against() -> None:
    """The one normal: the rail's usual and the engine's centre are one number."""

    rail = _hrv_rail(_row(TODAY, 46), _history())
    inputs = build_grading_inputs(
        subject_date=TODAY,
        acute={"overnightHrv": rail},
        last_night_hrv_ms=46,
        hrv_history={row.calendar_date: float(row.hrv_last_night_avg_ms) for row in _history()},
        sleep_score_raw=80,
        sleep_score_age_adjusted=80,
        sleep_minutes=450,
        sleep_minutes_history={},
        acwr=1.0,
        recovery_time_min=600,
        yesterday_load="easy",
        feel=8,
        feel_history={},
        readiness_level="HIGH",
        readiness_score=70,
        readiness_lower_quartile=55,
        planned_workouts=(),
        rest_day=False,
        blocks=(),
    )
    week = _hrv_week_on(inputs, TODAY, in_recovery_week=False)

    assert week.centre is not None
    assert round(week.centre, 2) == rail["usualMs"]


def test_a_low_night_is_quoted_against_his_usual() -> None:
    acute = _acute(overnight="capped")
    acute["overnightHrv"]["usualMs"] = 46.4

    phrase = mark_facing_phrase(_hrv_overnight(acute))

    assert phrase == "your HRV was low last night (40 ms against a usual 46)"


def test_a_morning_stored_before_the_one_normal_reads_its_median() -> None:
    """A stored rail has no ``usualMs``: a regrade of it quotes the median it carries."""

    phrase = mark_facing_phrase(_hrv_overnight(_acute(overnight="capped")))

    assert phrase == "your HRV was low last night (40 ms against a usual 47)"


def test_the_low_night_clause_of_a_low_week_quotes_his_usual() -> None:
    inputs = _inputs(week=44.5, overnight="capped")
    inputs.acute["overnightHrv"]["usualMs"] = 46.4

    verdict = grade(inputs)

    assert "(40 ms against a usual 46)" in verdict.summary
    assert "usual 47" not in verdict.summary


def test_a_recovery_week_says_which_usual_it_means() -> None:
    reading = SignalReading(
        domain=DOMAIN_AUTONOMIC,
        signal="hrv_7_day",
        rating="mild",
        value=41.2,
        reference="his recovery-week usual 44.0 ms, SD 3.0 ms",
        reason="",
        usual=44.0,
        recovery_week=True,
    )

    assert mark_facing_phrase(reading) == (
        "your HRV has been below your usual this week (41 ms against 44, your usual for a "
        "recovery week)"
    )


def test_an_ordinary_week_keeps_its_signed_off_words() -> None:
    reading = SignalReading(
        domain=DOMAIN_AUTONOMIC,
        signal="hrv_7_day",
        rating="marked",
        value=39.4,
        reference="his usual 46.3 ms, SD 4.8 ms",
        reason="",
        usual=46.3,
    )

    assert mark_facing_phrase(reading) == (
        "your HRV has been well below your usual this week (39 ms against 46)"
    )


def test_the_metrics_tables_hrv_row_is_centred_on_his_usual() -> None:
    rows = [
        {
            "metricKey": "hrv_7_day_avg_ms",
            "label": "HRV 7-day",
            "currentValue": 52,
            "baselineMedian": 47.0,
            "baselineMean": 47.2,
            "deltaVsBaseline": 5.0,
            "lowerQuartile": 45.0,
            "upperQuartile": 49.0,
            "sampleCount": 84,
        },
        {
            "metricKey": "sleep_score",
            "label": "Sleep score",
            "currentValue": 71,
            "baselineMedian": 74.0,
            "baselineMean": 73.1,
            "deltaVsBaseline": -3.0,
        },
    ]

    centred = morning_analysis.centre_hrv_row_on_usual(rows, 46.4)

    hrv, sleep = centred
    assert hrv["baselineMedian"] is None
    assert hrv["baselineMean"] == 46.4
    assert hrv["deltaVsBaseline"] == 5.6
    # Its usual range is still where his 7-day average usually sits.
    assert (hrv["lowerQuartile"], hrv["upperQuartile"]) == (45.0, 49.0)
    assert sleep == rows[1]
    # Without a usual (too few nights) the row is left as it was.
    assert morning_analysis.centre_hrv_row_on_usual(rows, None) == rows


def test_the_brief_is_told_his_usual_hrv_is_one_number() -> None:
    prompt = morning_analysis.SYSTEM_PROMPT

    assert morning_analysis.PROMPT_VERSION == "morning-analysis-v65-2026-10-29"
    assert morning_analysis.HRV_USUAL_RULE in prompt
    assert "acutePhysiology.overnightHrv.usualMs" in morning_analysis.HRV_USUAL_RULE


# -- the confirmed fair night -------------------------------------------------------------


def _sleep_domain(score: int, *, confirmed: bool) -> DomainRating:
    signal = SignalReading(
        domain=DOMAIN_SLEEP,
        signal="sleep_score",
        rating="mild",
        value=score,
        reference=None,
        reason=f"Sleep score {score} is fair.",
    )
    return DomainRating(
        domain=DOMAIN_SLEEP,
        rating="marked" if confirmed else "mild",
        signals=(signal,),
        confirmed_by_readiness=confirmed,
    )


def test_a_fair_night_readiness_confirms_has_its_own_words() -> None:
    summary = mark_facing_summary([_sleep_domain(65, confirmed=True)], rough=False)

    assert summary == (
        "One thing is clearly off: last night's sleep (score 65), which your readiness says "
        "left you less recovered than the score suggests."
    )


def test_a_fair_night_on_its_own_keeps_its_signed_off_words() -> None:
    summary = mark_facing_summary([_sleep_domain(72, confirmed=False)], rough=False)

    assert summary == "One thing is a little off: a fair night's sleep (score 72)."


def test_low_readiness_on_a_fair_night_reads_the_new_words_through_the_engine() -> None:
    verdict = grade(_inputs(sleep_score=70, readiness="LOW"))

    assert "last night's sleep (score 70), which your readiness says" in verdict.summary
    assert "fair" not in verdict.summary


@pytest.mark.parametrize(
    ("week", "sleep_score", "acwr", "readiness"),
    list(itertools.product([47.0, 44.5, 42.5], [80, 70, 55], [1.0, 1.6], ["HIGH", "LOW"])),
)
def test_clearly_off_never_names_a_fair_night(
    week: float, sleep_score: int, acwr: float, readiness: str
) -> None:
    """A fair night is "a little off": no clearly-off domain is worded as fair."""

    verdict = grade(_inputs(week=week, sleep_score=sleep_score, acwr=acwr, readiness=readiness))
    for item in verdict.domains:
        if item.rating == "marked":
            assert "fair" not in _domain_phrase(item), verdict.summary
    if "a little off" not in verdict.summary:
        assert "fair" not in verdict.summary


# -- Home's reason line -------------------------------------------------------------------


def _analysis(verdict: dict[str, Any]) -> Analysis:
    return Analysis(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        analysis_type="morning",
        subject_date=TODAY,
        generated_at_utc=datetime(2026, 10, 7, 7, 0, tzinfo=UTC),
        prompt_version=morning_analysis.PROMPT_VERSION,
        model_name="claude-sonnet-5",
        verdict="amber",
        context_packet={"verdict": verdict, "plannedWorkouts": []},
        output_markdown="",
        raw_response={},
    )


def test_the_daily_loop_sends_the_stored_reason() -> None:
    line = (
        "One thing is clearly off: your HRV has been well below your usual this week "
        "(39 ms against 46)."
    )
    out = _serialize_analysis(
        _analysis({"status": "Amber", "engine": "graded", "graded": {"summary": line}}),
        in_plan_week=True,
    )

    assert out.verdictSummary == line


def test_a_morning_the_ladder_graded_sends_no_reason() -> None:
    out = _serialize_analysis(
        _analysis({"status": "Amber", "reasons": ["Garmin readiness is Low."]}),
        in_plan_week=True,
    )

    assert out.verdictSummary is None


def test_the_domains_tuple_names_every_domain() -> None:
    """Guard for the sweep above: it covers every domain the engine rates."""

    assert {DOMAIN_AUTONOMIC, DOMAIN_SLEEP, DOMAIN_LOAD, DOMAIN_SUBJECTIVE} <= {
        item.domain for item in grade(_inputs()).domains
    }
