"""What the Experiments page says about an evaluation, in words Mark can read (Batch 385).

An evaluation's own ``reasons`` are for the coach's lookups and for Craig: they quote a
correlation as ``r=``, a range, a driver's key and a threshold. Batch 382 kept them out of the
experiment notice by building a plain sentence from the evidence
(``state_change_coach.plain_outcome_sentence``); this module does the same for the page, and
for every outcome the page can show, not only the two the notice is sent for.

Pure and DB-free. It reads the evaluation's ``kind``, ``status``, ``recommendation``,
``sample_count`` and ``evidence`` and returns:

- ``outcomeLabel``: the badge, in words (never a status key such as ``insufficient_history``);
- ``summary``: one or two plain sentences, or ``None`` when a figure the sentence needs is
  missing, so the page never falls back to the technical line;
- ``details``: labelled figures for a detail view, each in plain words. Empty when there is
  nothing to show.
"""

from __future__ import annotations

from typing import Any

from src.services.chronic_patterns import driver_label
from src.services.experiment_evaluation import (
    CORRELATION_MODERATE_R,
    CORRELATION_STRONG_R,
    KIND_CORRELATION,
    KIND_GATE,
    KIND_GROUP_COMPARE,
    KIND_INTERVENTION_COMPARE,
    RECOMMEND_INCONCLUSIVE,
    RECOMMEND_REFUTED,
    RECOMMEND_SUPPORTED,
    STATUS_INSUFFICIENT,
    STATUS_NO_EVALUATOR,
    STATUS_OK,
)
from src.services.state_change_coach import plain_outcome_sentence

#: The badge for each outcome. The three verdicts keep the words the page has always used;
#: the two states without a verdict said ``insufficient_history`` and ``no_evaluator``.
OUTCOME_LABELS = {
    RECOMMEND_SUPPORTED: "supported",
    RECOMMEND_REFUTED: "refuted",
    RECOMMEND_INCONCLUSIVE: "inconclusive",
    STATUS_INSUFFICIENT: "too early to tell",
    STATUS_NO_EVALUATOR: "no automatic check",
}

NO_EVALUATOR_SUMMARY = (
    "I can't check this one automatically, so it is for you to judge from your own notes."
)


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _nights(count: float) -> str:
    return f"{count:g} night" if count == 1 else f"{count:g} nights"


def _upper_first(text: str) -> str:
    return f"{text[:1].upper()}{text[1:]}"


def _correlations(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    raw = evidence.get("correlations")
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _interval_clears_zero(interval: Any) -> bool:
    if not isinstance(interval, list) or len(interval) != 2:
        return False
    low, high = _number(interval[0]), _number(interval[1])
    if low is None or high is None:
        return False
    return (low > 0 and high > 0) or (low < 0 and high < 0)


def _outcome_label(status: str, recommendation: str | None) -> str | None:
    if status == STATUS_OK and recommendation:
        return OUTCOME_LABELS.get(recommendation)
    return OUTCOME_LABELS.get(status)


def _too_early(kind: str, sample_count: float | None, evidence: dict[str, Any]) -> str | None:
    if kind == KIND_GROUP_COMPARE:
        recovery, build = (
            _number(evidence.get("recoveryNights")),
            _number(evidence.get("buildNights")),
        )
        if recovery is None or build is None:
            return None
        return (
            f"I have {_nights(recovery)} from recovery weeks and {_nights(build)} from build "
            "weeks so far, which is too few to compare yet."
        )
    if sample_count is None:
        return None
    return f"I have only {_nights(sample_count)} I can compare so far, which is too few to judge."


def _gate_inconclusive(evidence: dict[str, Any]) -> str | None:
    streak, nights, floor = (
        _number(evidence.get("currentStreak")),
        _number(evidence.get("gateNights")),
        _number(evidence.get("floor")),
    )
    if streak is None or nights is None or floor is None:
        return None
    if streak < 1:
        return (
            f"Your age-adjusted sleep score is below {floor:g} at the moment; the target is "
            f"{_nights(nights)} in a row at or above it."
        )
    return (
        f"Your age-adjusted sleep score has stayed at or above {floor:g} for "
        f"{_nights(streak)} in a row so far; the target is {nights:g}."
    )


def _correlation_inconclusive(evidence: dict[str, Any]) -> str:
    driver = evidence.get("strongestDriver")
    if not isinstance(driver, str) or not driver:
        return "I can't yet tell whether anything I measure lines up with the disturbed nights."
    label = driver_label(driver)
    top = _correlations(evidence)[:1]
    if top and _interval_clears_zero(top[0].get("interval")):
        return (
            f"{_upper_first(label)} moves with the disturbed nights, but only weakly, so it "
            "isn't strong enough to call a trigger."
        )
    return (
        f"I can't yet tell whether {label} or anything else I measure lines up with the "
        "disturbed nights."
    )


def _group_inconclusive(evidence: dict[str, Any], base: str) -> str:
    threshold, worse = _number(evidence.get("threshold")), _number(evidence.get("worseByDelta"))
    if threshold is None or worse is None:
        return base
    if abs(worse) >= threshold:
        return (
            f"{base} The gap looks big enough to matter, but there isn't enough data yet to be "
            "sure it is real."
        )
    return f"{base} That gap is too small to count as a real difference."


def _intervention_summary(evidence: dict[str, Any], recommendation: str, base: str) -> str:
    if recommendation != RECOMMEND_INCONCLUSIVE:
        return base
    if evidence.get("calendarApart") is True:
        return (
            f"{base} The nights you tried it fall in different weeks of the year, so the "
            "season could explain the difference."
        )
    return f"{base} That is too small, or too uncertain, to call either way."


def _intervention_too_few(evidence: dict[str, Any]) -> str | None:
    minimum = _number(evidence.get("minimumPerResponse"))
    if minimum is None:
        return None
    return (
        "There aren't enough nights yet to compare the nights you tried it with the nights "
        f"you didn't. I need at least {minimum:g} of each."
    )


def _summary(
    kind: str,
    status: str,
    recommendation: str | None,
    sample_count: float | None,
    evidence: dict[str, Any],
    packet: dict[str, Any],
) -> str | None:
    if status == STATUS_NO_EVALUATOR:
        return NO_EVALUATOR_SUMMARY
    if status == STATUS_INSUFFICIENT:
        return _too_early(kind, sample_count, evidence)
    if status != STATUS_OK or recommendation is None:
        return None
    if recommendation in (RECOMMEND_SUPPORTED, RECOMMEND_REFUTED):
        return plain_outcome_sentence(packet) or None
    if kind == KIND_GATE:
        return _gate_inconclusive(evidence)
    if kind == KIND_CORRELATION:
        return _correlation_inconclusive(evidence)
    base = plain_outcome_sentence(packet)
    if kind == KIND_GROUP_COMPARE:
        return _group_inconclusive(evidence, base) if base else None
    if kind == KIND_INTERVENTION_COMPARE:
        if base:
            return _intervention_summary(evidence, recommendation, base)
        return _intervention_too_few(evidence)
    return None


def _detail(label: str, value: str) -> dict[str, str]:
    return {"label": label, "value": value}


def _gate_details(evidence: dict[str, Any]) -> list[dict[str, str]]:
    details: list[dict[str, str]] = []
    streak, nights, floor = (
        _number(evidence.get("currentStreak")),
        _number(evidence.get("gateNights")),
        _number(evidence.get("floor")),
    )
    if streak is not None and floor is not None:
        details.append(_detail(f"Nights in a row at or above {floor:g}", f"{streak:g}"))
    if nights is not None:
        details.append(_detail("Target", f"{_nights(nights)} in a row"))
    latest, slope = _number(evidence.get("latestScore")), _number(evidence.get("recentSlope"))
    if latest is not None:
        details.append(_detail("Latest night's score", f"{latest:g}"))
    if slope is not None:
        trend = "rising" if slope > 0 else "falling" if slope < 0 else "flat"
        details.append(_detail("Recent trend", trend))
    return details


def _strength_word(coefficient: float) -> str:
    size = abs(coefficient)
    if size >= CORRELATION_STRONG_R:
        return "strong"
    if size >= CORRELATION_MODERATE_R:
        return "moderate"
    return "weak"


def _correlation_details(
    evidence: dict[str, Any], sample_count: float | None
) -> list[dict[str, str]]:
    details: list[dict[str, str]] = []
    driver = evidence.get("strongestDriver")
    if isinstance(driver, str) and driver:
        details.append(_detail("Closest match", _upper_first(driver_label(driver))))
        top = _correlations(evidence)[:1]
        if top:
            adjusted = _number(top[0].get("adjustedCoefficient"))
            coefficient = adjusted if adjusted is not None else _number(top[0].get("coefficient"))
            if coefficient is not None:
                details.append(
                    _detail(
                        "How closely it moves with the disturbed nights",
                        _strength_word(coefficient),
                    )
                )
    if sample_count is not None and driver:
        details.append(_detail("Nights compared", f"{sample_count:g}"))
    unmeasured = evidence.get("unmeasuredDrivers")
    if isinstance(unmeasured, list) and unmeasured:
        names = ", ".join(driver_label(item) for item in unmeasured if isinstance(item, str))
        if names:
            details.append(_detail("Not measured from your synced data", names))
    return details


def _group_details(evidence: dict[str, Any]) -> list[dict[str, str]]:
    details: list[dict[str, str]] = []
    units = evidence.get("units")
    unit = f" {units}" if isinstance(units, str) and units else ""
    recovery, build = _number(evidence.get("recoveryMean")), _number(evidence.get("buildMean"))
    recovery_n, build_n = (
        _number(evidence.get("recoveryNights")),
        _number(evidence.get("buildNights")),
    )
    if recovery is not None:
        over = f" over {_nights(recovery_n)}" if recovery_n is not None else ""
        details.append(_detail("Recovery weeks, average", f"{recovery:.1f}{unit}{over}"))
    if build is not None:
        over = f" over {_nights(build_n)}" if build_n is not None else ""
        details.append(_detail("Build weeks, average", f"{build:.1f}{unit}{over}"))
    delta = _number(evidence.get("delta"))
    if delta is not None:
        way = "higher" if delta > 0 else "lower" if delta < 0 else "the same"
        value = "no difference" if way == "the same" else f"{abs(delta):.1f}{unit} {way}"
        details.append(_detail("Recovery weeks against build weeks", value))
    threshold = _number(evidence.get("threshold"))
    if threshold is not None:
        details.append(_detail("A gap counts from", f"{threshold:g}{unit}"))
    return details


def _intervention_details(evidence: dict[str, Any]) -> list[dict[str, str]]:
    details: list[dict[str, str]] = []
    applied, not_applied = (
        _number(evidence.get("appliedNights")),
        _number(evidence.get("notAppliedNights")),
    )
    if applied is not None:
        details.append(_detail("Nights you tried it", f"{applied:g}"))
    if not_applied is not None:
        details.append(_detail("Nights you didn't", f"{not_applied:g}"))
    rem, awake = _number(evidence.get("remPctDelta")), _number(evidence.get("awakeMinDelta"))
    if rem is not None:
        way = "higher" if rem >= 0 else "lower"
        details.append(_detail("REM sleep on those nights", f"{abs(rem):.1f} points {way}"))
    if awake is not None:
        way = "longer" if awake >= 0 else "less"
        details.append(_detail("Time awake on those nights", f"{abs(awake):.0f} minutes {way}"))
    return details


def _details(
    kind: str, status: str, sample_count: float | None, evidence: dict[str, Any]
) -> list[dict[str, str]]:
    if status != STATUS_OK:
        return []
    if kind == KIND_GATE:
        return _gate_details(evidence)
    if kind == KIND_CORRELATION:
        return _correlation_details(evidence, sample_count)
    if kind == KIND_GROUP_COMPARE:
        return _group_details(evidence)
    if kind == KIND_INTERVENTION_COMPARE:
        return _intervention_details(evidence)
    return []


def plain_evaluation(
    *,
    kind: str,
    status: str,
    recommendation: str | None,
    sample_count: int | None,
    evidence: dict[str, Any] | None,
) -> dict[str, Any]:
    """The page's words for one evaluation (see the module note)."""

    facts = evidence if isinstance(evidence, dict) else {}
    count = _number(sample_count)
    packet = {"kind": kind, "recommendation": recommendation, "evidence": facts}
    return {
        "outcomeLabel": _outcome_label(status, recommendation),
        "summary": _summary(kind, status, recommendation, count, facts, packet),
        "details": _details(kind, status, count, facts),
    }
