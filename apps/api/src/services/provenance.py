"""Show the working behind a derived figure (Batch 273).

Mark's only remedy when a number looks wrong is to say so, and the coach's only
remedy is to agree with him and be powerless. The 7–13 September bedroom peak is
the case: a 21.4 °C "overnight" reading that was an afternoon sample, visible to
nobody, argued about for days. **A figure he can see the derivation of turns him
from a complainant into a debugger.**

**Provenance lives on the packet, never on the prose.** The brief and review render
model-written markdown; parsing numbers back out of generated text would be
fragile and would break on every prompt change. Each derived figure instead carries
its own structured derivation — which rows, over which window, under which rule,
against which threshold — beside the number, so it survives a prompt-version change
because it never depended on one.

**Some figures already carried their working, in bespoke shapes.** The acute HRV
rail has published `baselineMedianMs`, `baselineStddevMs`, `baselineSampleCount`,
`baselineWindowStartDate` and its `thresholds` block since Batch 122. That *is*
provenance; it simply had no common shape and no surface. So this module's job is
two-thirds adaptation and one-third addition, and `coach_sections`'s
`windowSource: "sleep" | "night_fallback"` is the seed it generalises.

**273.3 — what is covered, decided at `/batch-start` (Decision #345).** Full
coverage of every derived figure in the app is large and most of it has never been
disputed. Coverage starts with the figures that **have actually caused arguments**,
and :data:`DEFERRED_FIGURES` records what is not covered and why, in the code
rather than only in a document, so the next person adding a figure sees the list.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

#: A derived figure's stable key. Written ``section.figureName`` so a reader can
#: find it in the packet without a lookup table.
FIGURE_BEDROOM_PEAK = "environment.thermalReview.indoorPeakC"
FIGURE_REVIEW_AVG_PEAK = "review.thermal.avgIndoorPeakC"
FIGURE_REVIEW_DISRUPTION_NIGHTS = "review.thermal.disruptionNights"
FIGURE_HRV_ACUTE_FLOOR = "verdict.acutePhysiology.hrvAcuteFloorMs"
FIGURE_INTERVAL_GRADING = "execution.onTargetCount"

#: Every figure this app promises to show the working for. A figure added to a
#: covered producer without provenance fails :mod:`tests.test_batch_273_provenance`.
PROVENANCED_FIGURES: frozenset[str] = frozenset(
    {
        FIGURE_BEDROOM_PEAK,
        FIGURE_REVIEW_AVG_PEAK,
        FIGURE_REVIEW_DISRUPTION_NIGHTS,
        FIGURE_HRV_ACUTE_FLOOR,
        FIGURE_INTERVAL_GRADING,
    }
)

#: Not covered, and why. Deferral is a decision, so it is recorded next to the
#: thing it defers rather than in a document nobody opens (273.3).
DEFERRED_FIGURES: dict[str, str] = {
    "verdict.sleepCreditCeiling": (
        "Its inputs are the age-norm credit model, which is a table of population "
        "bands rather than a window of rows — a different provenance shape, and one "
        "Mark has questioned the *conclusion* of rather than the arithmetic. Cover it "
        "once the panel has shown which figures he actually presses (Batch 274/276)."
    ),
    "verdict.readinessEffectiveFloor": (
        "Derived from a baseline centre that already publishes its own window; it has "
        "never been disputed, and adding it now would be coverage for its own sake."
    ),
    "trends.*": (
        "The Trends narratives are model prose over rollups that themselves carry "
        "provenance once the rollups do. Cover the rollups first."
    ),
}


def _iso(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


@dataclass(frozen=True)
class Provenance:
    """The working behind one derived figure.

    Every field answers a question Mark could reasonably ask of a number:
    *what is it* (``label``/``value``/``units``), *what did you read*
    (``sources``), *over what stretch of time* (``window``), *what did you do with
    it* (``rule``), and *what did you compare it against* (``threshold``).
    """

    figure: str
    label: str
    value: Any
    rule: str
    sources: dict[str, Any]
    units: str | None = None
    window: dict[str, Any] | None = None
    threshold: dict[str, Any] | None = None

    def to_packet(self) -> dict[str, Any]:
        return {
            "figure": self.figure,
            "label": self.label,
            "value": self.value,
            "units": self.units,
            "rule": self.rule,
            "window": self.window,
            "sources": self.sources,
            "threshold": self.threshold,
        }


def window(
    *,
    kind: str,
    start: date | datetime | None = None,
    end: date | datetime | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    """The stretch of time a figure was derived over.

    ``kind`` is the *provenance* of the window itself, which is the distinction the
    7–13 September argument turned on: a figure measured over the real sleep window
    and one measured over a clock fallback are not the same figure, and a panel that
    cannot say which it used invites the reader to assume the better one.
    """
    return {
        "kind": kind,
        "startUtc": _iso(start),
        "endUtc": _iso(end),
        "label": label,
    }


def threshold(
    *,
    name: str,
    compared_against: float | int | None,
    units: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """The line a figure was measured against, and where that line came from."""
    return {
        "name": name,
        "comparedAgainst": compared_against,
        "units": units,
        "source": source,
    }


def provenance_packet(entries: list[Provenance]) -> list[dict[str, Any]]:
    """The packet-side list, ordered as given and safe to render as a panel."""
    return [entry.to_packet() for entry in entries]


def covered_figures(packet_provenance: list[dict[str, Any]] | None) -> set[str]:
    """Which covered figures a produced packet actually carries provenance for."""
    if not packet_provenance:
        return set()
    return {
        str(entry.get("figure"))
        for entry in packet_provenance
        if isinstance(entry, dict) and entry.get("figure")
    }
