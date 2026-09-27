"""One statement of what a figure currently means, carried by every surface (Batch 282).

Two prompts read overlapping packets and each drew its own conclusion about the same
number. On 26 Aug 2026 the brief called REM a chronic pattern, with 21 of 28 nights
below the band, while the Trends read, the same day and on the same data, concluded
"not a deficit". Batch 230 made both prompts embed one framing rule
(``age_norms.REM_FRAMING_RULE``), and a single test pinned that. The conclusion was
still reached twice, by two models from two packets. Here it is reached once: a
deterministic statement built by one function, carried by both packets and stated by
both prompts.

**What the batch-start measurement changed (27 Sep 2026).** The row counted 38 packet
keys on two or more of the morning, Trends and review packets, and named the
claim-carrying ones for scope: ``trend``, ``trendReason``, ``status``, ``delta``,
``pctChange``, ``bandLow``/``bandHigh`` and ``ageBand``. Traced to what each says,
only the **age-band position of a sleep-stage figure** is the same claim about the
same metric on two surfaces. The others share a name, not a claim. Each is recorded in
:data:`DEFERRED_CLAIM_KEYS` with its reason.

The covered set starts with REM because it is the figure that was contradicted, and
the only sleep stage with a personal baseline, so the only one whose statement has
both halves.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from src.models.coaching import MetricBaseline
from src.services.age_norms import age_band_label, describe_sleep_stage, sleep_stage_band

#: Every metric this app states one conclusion for, with the label the statement
#: uses. A metric added here that a surface does not state fails
#: ``tests/test_batch_282_metric_statements.py``.
COVERED_METRIC_STATEMENTS: dict[str, str] = {
    "rem_sleep_pct": "REM",
}

#: Claim-carrying keys the row named that are *not* one claim on two surfaces, and why.
#: Deferral is a decision, so it lives beside the thing it defers (the Batch 273
#: convention).
DEFERRED_CLAIM_KEYS: dict[str, str] = {
    "trend / trendReason": (
        "A different metric on each surface: breathwork on the morning brief, strength "
        "and the sleep and recovery halves on the weekly review. No metric carries "
        "the claim twice."
    ),
    "delta / pctChange": (
        "A different comparison on each surface: the review's first half against its "
        "second, and Trends' period against the same period last year. They are the "
        "same word, not the same claim."
    ),
    "status": (
        "A generic word with about thirty meanings across the services (coverage, "
        "generation, sync, evaluation). It carries no claim about a metric."
    ),
    "deep, light and awake stage bands": (
        "Only the morning brief states them. Trends reports no stage but REM, and "
        "none has a personal baseline, so no second surface can disagree yet."
    ),
}

#: Embedded verbatim by the morning and Trends system prompts, the Batch 230
#: pattern. A test pins both prompts to this string rather than to two paraphrases.
METRIC_STATEMENT_RULE = """\
metricStatements carries the app's one statement of where each covered figure sits: \
against the healthy range for his age band, and against his own usual range. The \
morning brief and the trends read are given statements built by the same function, \
so they must never reach different conclusions about the same figure. When you \
describe a figure that has a statement, give that statement's conclusion in your \
own plain words, with both of its halves and their numbers. Never drop the half \
that complicates the story, and never contradict it."""


def _position(value: float, low: float, high: float) -> str:
    if value < low:
        return "below"
    if value > high:
        return "above"
    return "within"


def _number(value: float) -> str:
    return f"{value:.1f}"


def _band_number(value: float) -> str:
    return f"{value:g}"


def sleep_stage_statement(
    metric_key: str,
    *,
    value: float | None,
    age: int | float | None,
    sex: str | None,
    baseline: MetricBaseline | None,
) -> dict[str, Any] | None:
    """Where one sleep-stage figure sits, stated once for every surface.

    The age half is ``age_norms``' own band judgement (the descriptor the stage
    table shows); the personal half places the figure against the interquartile
    range of his own stored history. ``None`` when there is no figure, or nothing to
    place it against.
    """
    if value is None:
        return None
    label = COVERED_METRIC_STATEMENTS.get(metric_key, metric_key)
    age_int = int(age) if isinstance(age, int | float) else None
    band = sleep_stage_band(metric_key, age_int, sex)
    described = describe_sleep_stage(metric_key, float(value), age_int, sex)
    low_q = baseline.lower_quartile_value if baseline is not None else None
    high_q = baseline.upper_quartile_value if baseline is not None else None
    has_personal = low_q is not None and high_q is not None

    halves: list[str] = []
    band_position: str | None = None
    band_claim: str | None = None
    if band is not None and described is not None and age_int is not None:
        band_position = _position(float(value), band[0], band[1])
        band_claim = described[1]
        halves.append(
            f"{band_claim[0].lower()}{band_claim[1:]} "
            f"({age_band_label(age_int)} band: "
            f"{_band_number(band[0])}–{_band_number(band[1])}%)"
        )
    personal_position: str | None = None
    if has_personal and low_q is not None and high_q is not None:
        personal_position = _position(float(value), float(low_q), float(high_q))
        halves.append(
            f"{personal_position} your own usual range "
            f"({_number(float(low_q))}–{_number(float(high_q))}%)"
        )
    if not halves:
        return None
    # "but" when the two halves point different ways (Batch 230: "normal for him AND
    # below the band" must be said as both, not resolved into one).
    joiner = (
        ", but "
        if band_position is not None
        and personal_position is not None
        and band_position != personal_position
        else ", and "
    )
    statement = f"{label} {_number(float(value))}% is " + joiner.join(halves) + "."
    return {
        "metricKey": metric_key,
        "label": label,
        "value": round(float(value), 2),
        "unit": "%",
        "ageBand": age_band_label(age_int) if age_int is not None and band else None,
        "bandLow": band[0] if band else None,
        "bandHigh": band[1] if band else None,
        "bandPosition": band_position,
        "bandClaim": band_claim,
        "personalLow": float(low_q) if low_q is not None else None,
        "personalHigh": float(high_q) if high_q is not None else None,
        "personalPosition": personal_position,
        "statement": statement,
    }


def metric_statements_packet(
    values: Mapping[str, float | None],
    *,
    age: Any,
    sex: Any,
    baselines: Iterable[MetricBaseline],
) -> list[dict[str, Any]]:
    """The ``metricStatements`` list both the brief and Trends carry."""
    by_key = {baseline.metric_key: baseline for baseline in baselines}
    statements: list[dict[str, Any]] = []
    for metric_key in COVERED_METRIC_STATEMENTS:
        statement = sleep_stage_statement(
            metric_key,
            value=values.get(metric_key),
            age=age if isinstance(age, int | float) else None,
            sex=sex if isinstance(sex, str) else None,
            baseline=by_key.get(metric_key),
        )
        if statement is not None:
            statements.append(statement)
    return statements


def missing_statements(statements: Sequence[Mapping[str, Any]]) -> set[str]:
    """Covered metrics a surface's ``metricStatements`` does not state."""
    stated = {entry.get("metricKey") for entry in statements}
    return {key for key in COVERED_METRIC_STATEMENTS if key not in stated}
