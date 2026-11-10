"""Batch 385 — the Experiments page says it in plain words.

Batch 382 took ``r=``, a range and a driver's key out of the experiment notice. The page still
showed an evaluation's own reasons, which quote them. ``plain_evaluation`` is what the page now
shows. Every fixture below is invented, and every evidence dict comes out of the real evaluator
so the shape is the one the page receives.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from src.models.coaching import Experiment
from src.routers.experiments import _evaluation_data
from src.services.experiment_evaluation import (
    KIND_CORRELATION,
    KIND_GATE,
    KIND_GROUP_COMPARE,
    KIND_INTERVENTION_COMPARE,
    RECOMMEND_INCONCLUSIVE,
    RECOMMEND_REFUTED,
    RECOMMEND_SUPPORTED,
    STATUS_INSUFFICIENT,
    STATUS_OK,
    EvaluationResult,
    LabeledNight,
    RemInterventionNight,
    SleepNight,
    _no_evaluator,
    evaluate_correlation,
    evaluate_gate_streak,
    evaluate_group_compare,
    evaluate_rem_interventions,
)
from src.services.experiment_metrics import COMPARABLE_METRICS
from src.services.experiment_plain_words import (
    NO_EVALUATOR_SUMMARY,
    OUTCOME_LABELS,
    plain_evaluation,
)
from src.services.internal_words import internal_words

HRV = COMPARABLE_METRICS["hrv_last_night_avg_ms"]
DAY = date(2026, 10, 1)

#: Anything a reader of a statistic would recognise, or a snake_case key, or a range.
TECHNICAL = re.compile(
    r"r\s?=|[+-]\d\.\d\d|\brange\b|standardised|interval|[a-z]+_[a-z]+|\bcorrelat",
    re.IGNORECASE,
)


def _words(result: EvaluationResult) -> dict[str, Any]:
    return plain_evaluation(
        kind=result.kind,
        status=result.status,
        recommendation=result.recommendation,
        sample_count=result.sample_count,
        evidence=result.evidence,
    )


def _all_text(plain: dict[str, Any]) -> list[str]:
    texts = [plain["outcomeLabel"] or "", plain["summary"] or ""]
    for item in plain["details"]:
        texts += [item["label"], item["value"]]
    return texts


def _assert_plain(plain: dict[str, Any]) -> None:
    for text in _all_text(plain):
        assert not TECHNICAL.search(text), text
        assert not internal_words(text).found, text


# -- fixtures from the real evaluators ---------------------------------------------------------


def _gate(streak: int, *, scores: list[float] | None = None) -> EvaluationResult:
    values = scores or ([70.0] * (8 - streak) + [78.0] * streak)
    nights = [SleepNight(day=DAY + timedelta(days=i), score=v) for i, v in enumerate(values)]
    return evaluate_gate_streak(nights, floor=75, gate_nights=7)


def _correlation(driver_values: list[float], outcome: list[float]) -> EvaluationResult:
    records: list[dict[str, float | None]] = [
        {"bedroom_peak_fan_speed": d, "overnight_awake_min": o}
        for d, o in zip(driver_values, outcome, strict=True)
    ]
    return evaluate_correlation(
        records,
        outcome_key="overnight_awake_min",
        driver_keys=("bedroom_peak_fan_speed",),
        unmeasured=("alcohol", "late_snack"),
    )


STEADY = [10.0, 14.0, 9.0, 16.0, 11.0, 15.0, 8.0, 13.0, 12.0, 17.0]
FAN = [1.0, 3.0, 1.0, 3.0, 2.0, 3.0, 1.0, 2.0, 2.0, 3.0]
FAN_UNRELATED = [2.0, 2.0, 1.0, 3.0, 2.0, 1.0, 3.0, 2.0, 1.0, 3.0]


def _groups(recovery: list[float], build: list[float]) -> list[LabeledNight]:
    return [
        LabeledNight(day=DAY + timedelta(days=i), value=v, group=group)
        for group, values in (("recovery", recovery), ("build", build))
        for i, v in enumerate(values)
    ]


def _rem(day: date, response: str, rem: float, awake: float = 20) -> RemInterventionNight:
    return RemInterventionNight(
        day=day, intervention_id="cool_room", response=response, rem_sleep_pct=rem, awake_min=awake
    )


def _interleaved(applied_rem: float, other_rem: float) -> list[RemInterventionNight]:
    return [
        _rem(
            DAY + timedelta(days=i),
            "applied" if i % 2 else "not_applied",
            (applied_rem if i % 2 else other_rem) + (i % 3) * 0.1,
        )
        for i in range(16)
    ]


# -- every kind of evaluation, in its own words --------------------------------------------------


def test_a_met_gate_and_one_still_building_read_in_plain_words() -> None:
    met = _words(_gate(7))
    assert met["outcomeLabel"] == "supported"
    assert met["summary"] == (
        "Your age-adjusted sleep score has stayed at or above 75 for 7 nights in a row, "
        "which meets the 7-night target."
    )
    building_result = _gate(3)
    assert building_result.recommendation == RECOMMEND_INCONCLUSIVE
    building = _words(building_result)
    assert building["summary"] == (
        "Your age-adjusted sleep score has stayed at or above 75 for 3 nights in a row so "
        "far; the target is 7 nights in a row."
    )
    assert {"label": "Nights in a row at or above 75", "value": "3"} in building["details"]
    assert {"label": "Target", "value": "7 nights in a row"} in building["details"]
    below = _words(_gate(0, scores=[78.0] * 7 + [60.0]))
    assert below["summary"] == (
        "Your age-adjusted sleep score is below 75 at the moment; the target is 7 nights in "
        "a row at or above it."
    )
    for plain in (met, building, below):
        _assert_plain(plain)


def test_a_gate_with_too_few_scored_nights_says_it_is_too_early() -> None:
    result = evaluate_gate_streak([SleepNight(day=DAY, score=80.0)], floor=75)
    assert result.status == STATUS_INSUFFICIENT
    plain = _words(result)
    assert plain["outcomeLabel"] == "too early to tell"
    assert (
        plain["summary"] == "I have only 1 night I can compare so far, which is too few to judge."
    )
    assert plain["details"] == []
    _assert_plain(plain)


def test_a_correlation_names_the_driver_in_words_and_never_quotes_a_statistic() -> None:
    supported_result = _correlation(FAN, [o + 6 * f for o, f in zip(STEADY, FAN, strict=True)])
    assert supported_result.recommendation == RECOMMEND_SUPPORTED
    supported = _words(supported_result)
    assert supported["summary"] == (
        "Fan speed moves closely with the disturbed nights, so it looks like a trigger."
    )
    assert {"label": "Closest match", "value": "Fan speed"} in supported["details"]
    assert {
        "label": "How closely it moves with the disturbed nights",
        "value": "strong",
    } in supported["details"]
    assert {
        "label": "Not measured from your synced data",
        "value": "alcohol, late snack",
    } in supported["details"]
    _assert_plain(supported)


def test_an_unclear_correlation_says_so_without_the_range() -> None:
    result = _correlation(FAN_UNRELATED, STEADY)
    assert result.recommendation == RECOMMEND_INCONCLUSIVE
    plain = _words(result)
    assert plain["outcomeLabel"] == "inconclusive"
    assert plain["summary"] == (
        "I can't yet tell whether fan speed or anything else I measure lines up with the "
        "disturbed nights."
    )
    _assert_plain(plain)


def test_a_weak_but_real_correlation_is_called_weak() -> None:
    evidence = {
        "strongestDriver": "bedroom_peak_fan_speed",
        "correlations": [
            {
                "driver": "bedroom_peak_fan_speed",
                "coefficient": 0.2,
                "adjustedCoefficient": None,
                "interval": [0.05, 0.35],
            }
        ],
        "unmeasuredDrivers": [],
    }
    plain = plain_evaluation(
        kind=KIND_CORRELATION,
        status=STATUS_OK,
        recommendation=RECOMMEND_INCONCLUSIVE,
        sample_count=120,
        evidence=evidence,
    )
    assert plain["summary"] == (
        "Fan speed moves with the disturbed nights, but only weakly, so it isn't strong "
        "enough to call a trigger."
    )
    assert {
        "label": "How closely it moves with the disturbed nights",
        "value": "weak",
    } in plain["details"]
    _assert_plain(plain)


def test_a_correlation_with_too_few_paired_nights_is_too_early() -> None:
    result = _correlation(FAN[:4], STEADY[:4])
    assert result.status == STATUS_INSUFFICIENT
    plain = _words(result)
    assert (
        plain["summary"] == "I have only 4 nights I can compare so far, which is too few to judge."
    )
    _assert_plain(plain)


def test_recovery_weeks_against_build_weeks_in_the_metrics_own_units() -> None:
    result = evaluate_group_compare(
        _groups(
            [36.0, 38.0, 35.0, 37.0, 36.0, 38.0, 35.0], [48.0, 50.0, 47.0, 49.0, 48.0, 50.0, 47.0]
        ),
        metric=HRV,
    )
    assert result.recommendation == RECOMMEND_SUPPORTED
    plain = _words(result)
    assert plain["summary"] == (
        "Your overnight HRV averaged 36.4 ms in recovery weeks against 48.4 ms in build weeks."
    )
    assert {"label": "Recovery weeks, average", "value": "36.4 ms over 7 nights"} in plain[
        "details"
    ]
    assert {"label": "Recovery weeks against build weeks", "value": "12.0 ms lower"} in plain[
        "details"
    ]
    _assert_plain(plain)


def test_a_small_gap_between_weeks_is_too_small_to_count_and_a_big_unsure_one_says_so() -> None:
    small = evaluate_group_compare(
        _groups(
            [47.0, 44.0, 51.0, 45.0, 49.0, 42.0, 53.0], [47.0, 44.0, 51.0, 45.0, 49.0, 42.0, 53.0]
        ),
        metric=HRV,
    )
    assert small.recommendation == RECOMMEND_INCONCLUSIVE
    assert _words(small)["summary"].endswith(
        " That gap is too small to count as a real difference."
    )
    unsure = evaluate_group_compare(
        _groups(
            [30.0, 60.0, 35.0, 55.0, 32.0, 58.0, 36.0], [47.0, 44.0, 51.0, 45.0, 49.0, 42.0, 53.0]
        ),
        metric=HRV,
    )
    assert unsure.recommendation == RECOMMEND_INCONCLUSIVE
    assert _words(unsure)["summary"].endswith(
        " The gap looks big enough to matter, but there isn't enough data yet to be sure it is "
        "real."
    )
    for result in (small, unsure):
        _assert_plain(_words(result))


def test_too_few_weeks_says_how_many_nights_each_side_has() -> None:
    result = evaluate_group_compare(_groups([40.0, 41.0], [48.0, 47.0, 49.0]), metric=HRV)
    assert result.status == STATUS_INSUFFICIENT
    plain = _words(result)
    assert plain["summary"] == (
        "I have 2 nights from recovery weeks and 3 nights from build weeks so far, which is "
        "too few to compare yet."
    )
    _assert_plain(plain)


def test_a_tried_lever_reads_as_nights_with_it_against_nights_without() -> None:
    result = evaluate_rem_interventions(_interleaved(16, 10))
    assert result.recommendation == RECOMMEND_SUPPORTED
    plain = _words(result)
    assert plain["summary"] is not None
    assert plain["summary"].startswith("On the nights you tried it, REM was ")
    assert {"label": "Nights you tried it", "value": "8"} in plain["details"]
    assert {"label": "Nights you didn't", "value": "8"} in plain["details"]
    _assert_plain(plain)


def test_an_unclear_lever_comparison_and_a_season_clash_each_say_why() -> None:
    unclear = evaluate_rem_interventions(_interleaved(12.1, 12.0))
    assert unclear.recommendation == RECOMMEND_INCONCLUSIVE
    assert _words(unclear)["summary"].endswith(
        " That is too small, or too uncertain, to call either way."
    )
    september = [_rem(DAY + timedelta(days=i), "not_applied", 10) for i in range(7)]
    october = [_rem(DAY + timedelta(days=40 + i), "applied", 16) for i in range(7)]
    apart = evaluate_rem_interventions([*september, *october])
    assert apart.evidence["calendarApart"] is True
    assert _words(apart)["summary"].endswith(
        " The nights you tried it fall in different weeks of the year, so the season could "
        "explain the difference."
    )
    for result in (unclear, apart):
        _assert_plain(_words(result))


def test_a_lever_without_enough_nights_in_each_arm_says_how_many_it_needs() -> None:
    few = evaluate_rem_interventions(
        [_rem(DAY, "applied", 14), _rem(DAY + timedelta(days=1), "not_applied", 11)]
    )
    plain = _words(few)
    assert plain["outcomeLabel"] == "inconclusive"
    assert plain["summary"] == (
        "There aren't enough nights yet to compare the nights you tried it with the nights "
        "you didn't. I need at least 7 of each."
    )
    assert plain["details"] == []  # the counts sit per lever, not on the whole comparison
    _assert_plain(plain)


def test_an_experiment_with_no_automatic_check_says_it_is_yours_to_judge() -> None:
    plain = _words(_no_evaluator("anything"))
    assert plain == {
        "outcomeLabel": "no automatic check",
        "summary": NO_EVALUATOR_SUMMARY,
        "details": [],
    }
    _assert_plain(plain)


# -- a missing figure shows nothing, never the technical line ------------------------------------


@pytest.mark.parametrize(
    ("kind", "recommendation"),
    [
        (KIND_GATE, RECOMMEND_SUPPORTED),
        (KIND_GATE, RECOMMEND_INCONCLUSIVE),
        (KIND_GROUP_COMPARE, RECOMMEND_REFUTED),
        (KIND_GROUP_COMPARE, RECOMMEND_INCONCLUSIVE),
        (KIND_INTERVENTION_COMPARE, RECOMMEND_SUPPORTED),
        (KIND_INTERVENTION_COMPARE, RECOMMEND_INCONCLUSIVE),
    ],
)
def test_a_missing_figure_leaves_the_summary_empty(kind: str, recommendation: str) -> None:
    plain = plain_evaluation(
        kind=kind,
        status=STATUS_OK,
        recommendation=recommendation,
        sample_count=9,
        evidence={},
    )
    assert plain["summary"] is None
    assert plain["details"] == []


def test_no_evidence_at_all_gives_a_label_and_nothing_else() -> None:
    plain = plain_evaluation(
        kind=KIND_GROUP_COMPARE,
        status=STATUS_INSUFFICIENT,
        recommendation=None,
        sample_count=None,
        evidence=None,
    )
    assert plain == {"outcomeLabel": "too early to tell", "summary": None, "details": []}


def test_every_label_is_plain_and_the_status_keys_never_reach_the_badge() -> None:
    assert set(OUTCOME_LABELS) == {
        "supported",
        "refuted",
        "inconclusive",
        STATUS_INSUFFICIENT,
        "no_evaluator",
    }
    for label in OUTCOME_LABELS.values():
        assert "_" not in label


# -- what the endpoint sends ---------------------------------------------------------------------


def test_the_endpoint_carries_the_plain_block_beside_the_coach_s_own_reasons() -> None:
    result = _gate(3)
    experiment = Experiment(
        id=__import__("uuid").uuid4(),
        user_id=__import__("uuid").uuid4(),
        title="Sleep gate",
        hypothesis="h",
        status="active",
    )
    data = _evaluation_data(experiment, result, None)
    assert data.plain.summary is not None and "7" in data.plain.summary
    assert data.plain.outcomeLabel == "inconclusive"
    # The coach's own text is unchanged: the technical reasons stay for its lookups.
    assert data.reasons == result.reasons
    assert any("streak" in reason for reason in data.reasons)


def test_the_notice_sentence_keeps_an_acronym_and_one_decimal() -> None:
    """Found at re-verification: the real metric label is "overnight HRV", which the
    Batch 382 sentence lower-cased to "overnight hrv", and the evidence holds two decimals."""
    from src.services.state_change_coach import plain_outcome_sentence

    sentence = plain_outcome_sentence(
        {
            "kind": KIND_GROUP_COMPARE,
            "recommendation": RECOMMEND_REFUTED,
            "evidence": {
                "metricLabel": "overnight HRV",
                "units": "ms",
                "recoveryMean": 44.13,
                "buildMean": 51.17,
            },
        }
    )
    assert sentence == (
        "Your overnight HRV averaged 44.1 ms in recovery weeks against 51.2 ms in build weeks."
    )


# -- the words are the draft's ---------------------------------------------------------------------

DRAFT = Path(__file__).resolve().parents[3] / "docs" / "drafts" / "2026-11-10-batch-385-wording.md"


def _draft_text() -> str:
    return " ".join(DRAFT.read_text(encoding="utf-8").replace("*", "").split())


def _sentences(text: str) -> list[str]:
    return re.split(r"(?<=\.)\s+(?=[A-Z])", text)


def _built(kind: str, recommendation: str | None, evidence: dict[str, Any], **kw: Any) -> str:
    plain = plain_evaluation(
        kind=kind,
        status=kw.get("status", STATUS_OK),
        recommendation=recommendation,
        sample_count=kw.get("sample_count", 10),
        evidence=evidence,
    )
    assert plain["summary"], (kind, recommendation, evidence)
    return plain["summary"]


def test_every_sentence_the_page_can_say_is_in_the_signed_off_draft() -> None:
    weeks = {
        "metricLabel": "overnight HRV",
        "units": "ms",
        "recoveryMean": 36.4,
        "buildMean": 48.4,
        "recoveryNights": 7,
        "buildNights": 7,
        "threshold": 3.0,
    }
    lever = {"remPctDelta": 2.4, "awakeMinDelta": -12.0, "minimumPerResponse": 7}
    gate = {"currentStreak": 3, "gateNights": 7, "floor": 75}
    weak = {
        "strongestDriver": "bedroom_peak_fan_speed",
        "correlations": [{"interval": [0.05, 0.35], "coefficient": 0.2}],
    }
    built = [
        _built(KIND_GATE, RECOMMEND_SUPPORTED, {**gate, "currentStreak": 7}),
        _built(KIND_GATE, RECOMMEND_INCONCLUSIVE, gate),
        _built(KIND_GATE, RECOMMEND_INCONCLUSIVE, {**gate, "currentStreak": 0}),
        _built(
            KIND_CORRELATION, RECOMMEND_SUPPORTED, {"strongestDriver": "bedroom_peak_fan_speed"}
        ),
        _built(KIND_CORRELATION, RECOMMEND_REFUTED, {}),
        _built(KIND_CORRELATION, RECOMMEND_INCONCLUSIVE, weak),
        _built(
            KIND_CORRELATION,
            RECOMMEND_INCONCLUSIVE,
            {"strongestDriver": "bedroom_peak_fan_speed", "correlations": []},
        ),
        _built(KIND_CORRELATION, RECOMMEND_INCONCLUSIVE, {}),
        _built(KIND_GROUP_COMPARE, RECOMMEND_SUPPORTED, weeks),
        _built(KIND_GROUP_COMPARE, RECOMMEND_INCONCLUSIVE, {**weeks, "worseByDelta": 12.0}),
        _built(KIND_GROUP_COMPARE, RECOMMEND_INCONCLUSIVE, {**weeks, "worseByDelta": 1.0}),
        _built(KIND_INTERVENTION_COMPARE, RECOMMEND_SUPPORTED, lever),
        _built(KIND_INTERVENTION_COMPARE, RECOMMEND_INCONCLUSIVE, lever),
        _built(KIND_INTERVENTION_COMPARE, RECOMMEND_INCONCLUSIVE, {**lever, "calendarApart": True}),
        _built(
            KIND_INTERVENTION_COMPARE,
            RECOMMEND_INCONCLUSIVE,
            {"minimumPerResponse": 7, "interventions": []},
        ),
        _built(KIND_GATE, None, {}, status=STATUS_INSUFFICIENT, sample_count=4),
        _built(
            KIND_GROUP_COMPARE,
            None,
            {"recoveryNights": 2, "buildNights": 3},
            status=STATUS_INSUFFICIENT,
        ),
        NO_EVALUATOR_SUMMARY,
    ]
    draft = _draft_text()
    for summary in built:
        for sentence in _sentences(summary):
            assert sentence in draft, sentence
    for label in OUTCOME_LABELS.values():
        assert label in draft


def test_the_detail_labels_are_the_drafts() -> None:
    draft = _draft_text()
    detail_sets = [
        _gate(3).evidence | {"latestScore": 78, "recentSlope": 0.4},
    ]
    labels: set[str] = set()
    for result in (
        _gate(3),
        _correlation(FAN, [o + 6 * f for o, f in zip(STEADY, FAN, strict=True)]),
    ):
        labels |= {item["label"] for item in _words(result)["details"]}
    labels |= {
        item["label"]
        for item in plain_evaluation(
            kind=KIND_GROUP_COMPARE,
            status=STATUS_OK,
            recommendation=RECOMMEND_SUPPORTED,
            sample_count=14,
            evidence={
                "units": "ms",
                "recoveryMean": 36.4,
                "buildMean": 48.4,
                "recoveryNights": 7,
                "buildNights": 7,
                "delta": -12.0,
                "threshold": 3.0,
            },
        )["details"]
    }
    labels |= {
        item["label"]
        for item in plain_evaluation(
            kind=KIND_INTERVENTION_COMPARE,
            status=STATUS_OK,
            recommendation=RECOMMEND_SUPPORTED,
            sample_count=16,
            evidence={
                "appliedNights": 8,
                "notAppliedNights": 8,
                "remPctDelta": 2.4,
                "awakeMinDelta": -12.0,
            },
        )["details"]
    }
    del detail_sets
    assert len(labels) >= 13
    for label in labels:
        assert label in draft, label
