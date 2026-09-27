"""The app checks its own figures against each other before a paid read (Batch 272).

For a fortnight in September 2026 the weekly review put Mark's bedroom about 2 °C
warmer every night than the morning brief had, from the same temperature readings:
7-13 Sep averaged 20.9 °C in the review against the briefs' 18.8, and "5 of 7 nights
showed thermal disruption" on nights that never reached 20 °C. Nothing in the app
noticed. Mark did, three times. Batch 268 fixed that bug; this module is the check
that would have caught it on the first Sunday, and will catch the next one.

**One family of check: cross-surface agreement.** Where two surfaces derive the same
quantity from the same table, they must agree within a stated tolerance. That can be
checked without knowing anything about bedrooms, which is what makes it general:
:data:`AGREEMENT_PAIRS` is the registry, :func:`evaluate_agreement` is the one code
path every pair goes through, and a new surface that derives a registered quantity is
checked the day it is added rather than the fortnight after it drifts.

**It runs on the assembled packet, before the model is called, and costs nothing:**
no model call, and no query of its own. Each surface hands it rows it has already
loaded, and both derivations are recomputed from those rows. It deliberately does
*not* compare against the briefs stored on earlier mornings. Measured on 27 Sep 2026
over 98 nights, every stored brief since 13 Jul matches the shared night calculation
within 0.1 °C, but the 15 briefs written from 25 Jun to 12 Jul do not, because the
brief's own night window changed on 13 Jul. A check against stored packets would mark
every window reaching back that far unreliable for ever, although today's figure is
the right one.

**What a failed check does (272.3, decided at ``/batch-start``): mark and alert, never
block.** The packet carries ``crossSurfaceAgreement`` with every check, its findings
and the packet fields they make unreliable; each prompt embeds
:data:`CROSS_SURFACE_AGREEMENT_RULE`, so the read says the app's figures disagree
instead of asserting either. :func:`alert_disagreements` logs each finding at error
level, which reaches Sentry; a push route for operator alerts is Batch 291's. A
blocked weekly review is a worse outcome for Mark than one caveated figure, and
blocking would hand a data-quality bug the power to remove his coaching.

**This is not the knowledge base's ``data_quality_rules`` (272.4).** That section is
advisory prose the model reads (``trends._data_quality_guardrails`` and the review's
equivalent): it steers what a narrative *says* and is powerless over what a
deterministic rollup *computes*. The 5-of-7 disruption count came out of the rollup,
and no prose rule could have stopped it. This module is the enforcement layer that
section never had.
"""

from __future__ import annotations

import uuid
from bisect import bisect_left
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import fmean
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog

from src.models.coaching import Sleep, TemperatureReading
from src.services.bedroom_overnight import night_window
from src.services.coach_sections import thermal_review
from src.services.night_thermal import night_indoor_peaks

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class Derivation:
    """One way the app works a quantity out, and which screens show it."""

    surfaces: str
    source: str


@dataclass(frozen=True)
class AgreementPair:
    """Two derivations of one quantity from one table, and how far apart they may be."""

    key: str
    label: str
    units: str
    tolerance: float
    derivations: tuple[Derivation, Derivation]


PAIR_BEDROOM_PEAK = "bedroom_night_peak_c"
BRIEF = 0
SHARED_NIGHT = 1

#: Every quantity two surfaces derive separately. A surface that starts deriving one
#: of these gets checked by the same code path; a new quantity is a new entry here.
AGREEMENT_PAIRS: dict[str, AgreementPair] = {
    PAIR_BEDROOM_PEAK: AgreementPair(
        key=PAIR_BEDROOM_PEAK,
        label="bedroom peak overnight",
        units="°C",
        # The two derivations read the same readings over the same window, so they
        # agree exactly when both are right; the headroom is for the review's and
        # Trends' rounding. The September divergence was 1.4-2.8 °C a night.
        tolerance=0.15,
        derivations=(
            Derivation(
                surfaces="the morning brief",
                source="coach_sections.thermal_review",
            ),
            Derivation(
                surfaces="the weekly review and Trends",
                source="night_thermal.night_indoor_peaks",
            ),
        ),
    ),
}

#: Quantities that look like pairs and are not, and why. Deferral is a decision, so
#: it lives beside the thing it defers (the Batch 273 and 282 convention).
DEFERRED_PAIRS: dict[str, str] = {
    "age-adjusted sleep score": (
        "One derivation, not two: the brief and the weekly review both call "
        "sleep_scoring.age_adjusted_sleep_score on the same sleep row and profile."
    ),
    "overnight HRV, resting heart rate, readiness and the raw sleep score": (
        "Read straight from one column by every surface, from the morning row since "
        "Batch 205, so there is no second calculation to drift."
    ),
    "REM share of sleep": (
        "Batch 282 made it one statement built by one function for both the brief "
        "and Trends, and its test holds the two identical."
    ),
}

#: Embedded verbatim by the morning, review and Trends system prompts, the Batch 230
#: pattern, so the three reads treat a finding the same way.
CROSS_SURFACE_AGREEMENT_RULE = """\
crossSurfaceAgreement records the app checking its own figures against each other \
before this read was written: where two parts of the app work out the same number \
from the same data, the two must agree. Each entry in its findings is a figure that \
failed that check, with both values and the parts of the app that produced them, and \
unreliableFigures lists the packet fields it affects. Never state an unreliable \
figure as fact or build a conclusion on it: say plainly that the app's own figures \
for it disagree, give both values, and say it has been flagged to be checked. When \
findings is empty, say nothing about the check."""


@dataclass(frozen=True)
class NightValues:
    night: date
    stated: float
    reference: float


@dataclass(frozen=True)
class AgreementCheck:
    """One figure a packet states, against the same quantity derived the other way."""

    pair: str
    figures: tuple[str, ...]
    scope: str
    stated: float | None
    reference: float | None
    stated_by: int
    nights_compared: int = 1
    disagreeing_nights: tuple[NightValues, ...] = ()


def evaluate_agreement(checks: Sequence[AgreementCheck]) -> dict[str, Any]:
    """The packet section: every check made, what failed, and what it affects.

    Written against the registry only. Nothing here knows what a bedroom is, so a pair
    registered tomorrow is judged by exactly this code.
    """
    checked: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    unreliable: set[str] = set()
    for check in checks:
        pair = AGREEMENT_PAIRS[check.pair]
        stated_by = pair.derivations[check.stated_by]
        reference_by = pair.derivations[1 - check.stated_by]
        entry: dict[str, Any] = {
            "pair": pair.key,
            "label": pair.label,
            "units": pair.units,
            "scope": check.scope,
            "figures": list(check.figures),
            "stated": {
                "value": check.stated,
                "by": stated_by.surfaces,
                "source": stated_by.source,
            },
            "reference": {
                "value": _round(check.reference),
                "by": reference_by.surfaces,
                "source": reference_by.source,
            },
            "tolerance": pair.tolerance,
            "nightsCompared": check.nights_compared,
        }
        if check.stated is None or check.reference is None:
            entry["status"] = "not_comparable"
            checked.append(entry)
            continue
        # ``+ 0.0`` so an agreement reads 0.0 rather than -0.0 in the packet.
        difference = round(check.stated - check.reference, 2) + 0.0
        entry["difference"] = difference
        entry["status"] = "agrees" if abs(difference) <= pair.tolerance else "disagrees"
        checked.append(entry)
        if entry["status"] == "disagrees":
            findings.append(
                {
                    **entry,
                    "disagreeingNights": [
                        {
                            "night": night.night.isoformat(),
                            "stated": night.stated,
                            "reference": _round(night.reference),
                        }
                        for night in check.disagreeing_nights
                    ],
                }
            )
            unreliable.update(check.figures)
    return {
        "checked": checked,
        "findings": findings,
        "unreliableFigures": sorted(unreliable),
    }


def alert_disagreements(
    section: Mapping[str, Any] | None,
    *,
    surface: str,
    user_id: uuid.UUID,
    subject: str,
) -> int:
    """Tell the operator, before the paid call, that a read is about to caveat a figure.

    An ``error``-level event, which reaches Sentry. It never raises and never blocks:
    the read goes ahead with the figure marked.
    """
    findings = section.get("findings") if isinstance(section, Mapping) else None
    if not isinstance(findings, list):
        return 0
    for finding in findings:
        stated = finding.get("stated") or {}
        reference = finding.get("reference") or {}
        log.error(
            "cross_surface_disagreement",
            surface=surface,
            user_id=str(user_id),
            subject=subject,
            pair=finding.get("pair"),
            scope=finding.get("scope"),
            figures=finding.get("figures"),
            stated=stated.get("value"),
            stated_by=stated.get("source"),
            reference=reference.get("value"),
            reference_by=reference.get("source"),
            difference=finding.get("difference"),
            tolerance=finding.get("tolerance"),
        )
    return len(findings)


# -- the bedroom peak, both ways ---------------------------------------------------


def brief_night_peaks(
    temperature_rows: Sequence[TemperatureReading],
    sleeps: Sequence[Sleep],
    *,
    start: date,
    end: date,
    timezone_name: str,
) -> dict[date, float]:
    """The morning brief's own bedroom peak for each night, keyed by the wake date.

    What ``MorningAnalysisService`` does for one morning, done for each: the readings
    its query selects (the 21:30-09:00 ``night_window``, end exclusive), handed to
    ``coach_sections.thermal_review`` with that morning's sleep row. A night with no
    reading is absent, as in ``night_indoor_peaks``.
    """
    tz = _zone(timezone_name)
    sleep_by_wake_date = {row.calendar_date: row for row in sleeps}
    rows = sorted(temperature_rows, key=lambda row: row.captured_at_utc)
    # Trends hands over up to 800 days of readings, so each night's slice is found by
    # binary search rather than by scanning every reading once per night.
    stamps = [row.captured_at_utc for row in rows]
    peaks: dict[date, float] = {}
    wake_date = start
    while wake_date <= end:
        window_start, window_end = night_window(wake_date - timedelta(days=1), tz)
        in_window = rows[bisect_left(stamps, window_start) : bisect_left(stamps, window_end)]
        if in_window:
            peak = thermal_review(in_window, None, {}, sleep=sleep_by_wake_date.get(wake_date))[
                "indoorPeakC"
            ]
            if isinstance(peak, int | float):
                peaks[wake_date] = float(peak)
        wake_date += timedelta(days=1)
    return peaks


def morning_bedroom_check(
    thermal: Mapping[str, Any] | None,
    temperature_rows: Sequence[TemperatureReading],
    sleep: Sleep | None,
    *,
    subject_date: date,
    timezone_name: str,
) -> list[AgreementCheck]:
    """The brief's stated peak against the night calculation the review and Trends use.

    Nothing to check when the brief states no peak (a holiday, or an unmeasured night).
    """
    stated = thermal.get("indoorPeakC") if isinstance(thermal, Mapping) else None
    if not isinstance(stated, int | float):
        return []
    shared = night_indoor_peaks(
        temperature_rows,
        [sleep] if sleep is not None else [],
        start=subject_date,
        end=subject_date,
        timezone_name=timezone_name,
    ).get(subject_date)
    reference = shared.peak_c if shared is not None else None
    disagreeing = (
        (NightValues(subject_date, float(stated), reference),)
        if reference is not None
        and abs(float(stated) - reference) > AGREEMENT_PAIRS[PAIR_BEDROOM_PEAK].tolerance
        else ()
    )
    return [
        AgreementCheck(
            pair=PAIR_BEDROOM_PEAK,
            figures=("environment.thermalReview.indoorPeakC",),
            scope=f"the night ending {subject_date.isoformat()}",
            stated=float(stated),
            reference=reference,
            stated_by=BRIEF,
            disagreeing_nights=disagreeing,
        )
    ]


def period_bedroom_check(
    *,
    figures: Sequence[str],
    scope: str,
    stated: float | None,
    shared_nights: Mapping[date, float],
    brief_nights: Mapping[date, float],
) -> AgreementCheck | None:
    """A period's stated average peak against the brief's peaks for the same nights.

    ``shared_nights`` are the per-night peaks the period's figure was averaged from;
    the reference is the brief's peak for each of those nights. ``None`` when the
    period states no peak.
    """
    if stated is None:
        return None
    common = sorted(night for night in shared_nights if night in brief_nights)
    reference = fmean(brief_nights[night] for night in common) if common else None
    tolerance = AGREEMENT_PAIRS[PAIR_BEDROOM_PEAK].tolerance
    disagreeing = tuple(
        NightValues(night, shared_nights[night], brief_nights[night])
        for night in common
        if abs(shared_nights[night] - brief_nights[night]) > tolerance
    )
    return AgreementCheck(
        pair=PAIR_BEDROOM_PEAK,
        figures=tuple(figures),
        scope=scope,
        stated=float(stated),
        reference=reference,
        stated_by=SHARED_NIGHT,
        nights_compared=len(common),
        disagreeing_nights=disagreeing,
    )


def _round(value: float | None) -> float | None:
    return round(value, 2) + 0.0 if value is not None else None


def _zone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")
