"""The written morning brief, checked against the morning it was written from (Batch 318).

After the paid call the only check was a logged warning for a missing heading
(``morning_output_contract.missing_morning_output_sections``). Nothing noticed a brief
whose call drifted from the stored one, named a colour Mark is never shown, or quoted an
HRV, sleep or resting-heart-rate figure the morning never held. This module checks each,
deterministically, over the stored packet and the written markdown. A miss is raised to
Craig through ``admin_alert`` and stored beside the brief; it never blocks the brief,
because Mark is waiting for it and the call itself was already shown, from the packet.

The checks (318.3):

* ``call_not_first``: the brief's first section is not "Today's call";
* ``call_opening``: the call section does not open with the stored headline and reading;
* ``call_too_long``: the call section is over
  :data:`~src.services.morning_output_contract.CALL_SECTION_MAX_WORDS` words;
* ``colour_words``: Green, Amber, Red or verdict appear outside the stored headline;
* ``unknown_figures``: an HRV (ms), resting-heart-rate (bpm) or sleep-score figure the
  packet does not hold;
* ``statistics_words``: median, quartile, percentile, standard deviation or a sample count
  (Batch 369.2, ST363-08b, UX362-04: "median" reached 4 of 6 briefs after the plain-words
  rule shipped, and the rule's own detector only logged);
* ``readiness_in_call``: the call restates the six-week readiness trend, which the app
  places under the next heading itself (Batch 377.1);
* ``engine_words``: "domain" or "autonomic", the graded engine's words (Batch 377.2: both
  survived v67's two rules against them);
* ``call_shape``: the call has no sentence opening "Because" or "This would change it:"
  (Batch 377.3: 3 of the 4 repairs kept in 369's replays dropped one);
* ``internal_words``: the app's own words for what it was given — "packet", a field name, a
  raw source label, an ``r=`` figure (Batch 382: the 7 Nov brief said "the packet only gives
  me today's planned sessions"; ``services.internal_words`` holds the rule).

Pure: no database, no model call. The brief's eval (``services.brief_eval``) scores its
recorded answers with the same function.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from src.services.coach_policy import statistics_wording_leaks
from src.services.internal_words import internal_words
from src.services.morning_output_contract import CALL_SECTION_MAX_WORDS, TODAYS_CALL_HEADING

MISS_CALL_NOT_FIRST: Final = "call_not_first"
MISS_CALL_OPENING: Final = "call_opening"
MISS_CALL_TOO_LONG: Final = "call_too_long"
MISS_COLOUR_WORDS: Final = "colour_words"
MISS_UNKNOWN_FIGURES: Final = "unknown_figures"
MISS_STATISTICS_WORDS: Final = "statistics_words"
MISS_READINESS_IN_CALL: Final = "readiness_in_call"
MISS_ENGINE_WORDS: Final = "engine_words"
MISS_CALL_SHAPE: Final = "call_shape"
MISS_INTERNAL_WORDS: Final = "internal_words"
MISSES: Final = (
    MISS_CALL_NOT_FIRST,
    MISS_CALL_OPENING,
    MISS_CALL_TOO_LONG,
    MISS_COLOUR_WORDS,
    MISS_UNKNOWN_FIGURES,
    MISS_STATISTICS_WORDS,
    MISS_READINESS_IN_CALL,
    MISS_ENGINE_WORDS,
    MISS_CALL_SHAPE,
    MISS_INTERNAL_WORDS,
)

_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(?P<heading>.+?)\s*#*\s*$", re.MULTILINE)
#: The engine's words Mark is never shown (Batch 313). Capitalised colours only: "red"
#: in running prose ("a red-letter day") is not the engine's word.
_COLOUR_CASED = re.compile(r"\b(?:Green|Amber|Red)\b")
_VERDICT = re.compile(r"\bverdicts?\b", re.IGNORECASE)
_HRV = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d+)?)\s?ms\b")
_BPM = re.compile(r"(?<![\d.])(\d{2,3}(?:\.\d+)?)\s?bpm\b", re.IGNORECASE)
_SCORE = re.compile(r"\bscore(?:\s+(?:of|was|is|at))?\s+(\d{1,3})\b", re.IGNORECASE)
#: Batch 377.2: the graded engine's own words for what it rates.
_ENGINE_WORDS = re.compile(r"\b(?:domains?|autonomic)\b", re.IGNORECASE)
_READINESS = re.compile(r"\breadiness\b", re.IGNORECASE)
_SIX_WEEKS = re.compile(r"\b(?:six|6)[- ]weeks?\b", re.IGNORECASE)
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")
#: Batch 318's call says why in a sentence opening "Because" and what would move it in one
#: opening "This would change it:" (TODAYS_CALL_INSTRUCTION); "Tonight:" may be left out.
CALL_OPENINGS: Final = ("Because", "This would change it:")
_OPENING_PATTERNS: Final = tuple(
    re.compile(
        r"(?:^|[.!?]\s+)(?:[-*+>]\s+)?"
        + r"\s+".join(re.escape(word) for word in opening.split())
        + r"(?!\w)",
        re.MULTILINE,
    )
    for opening in CALL_OPENINGS
)


@dataclass(frozen=True, slots=True)
class BriefCheck:
    """What the check found: the misses, and the evidence for each."""

    misses: tuple[str, ...]
    call_words: int | None = None
    colour_words: tuple[str, ...] = ()
    unknown_figures: tuple[str, ...] = ()
    statistics_words: tuple[str, ...] = ()
    engine_words: tuple[str, ...] = ()
    missing_openings: tuple[str, ...] = ()
    internal_words: tuple[str, ...] = ()
    details: Mapping[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.misses

    def to_packet(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "misses": list(self.misses),
            "callWords": self.call_words,
            "colourWords": list(self.colour_words),
            "unknownFigures": list(self.unknown_figures),
            "statisticsWords": list(self.statistics_words),
            "engineWords": list(self.engine_words),
            "missingOpenings": list(self.missing_openings),
            "internalWords": list(self.internal_words),
        }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _normalise(text: str) -> str:
    return text.replace("’", "'").replace("‘", "'").replace("—", "-")


def _sections(markdown: str) -> list[tuple[str, str]]:
    """``(heading, body)`` for every heading, in order."""

    matches = list(_HEADING.finditer(markdown))
    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        sections.append((match.group("heading").strip(), markdown[match.end() : end]))
    return sections


def _is_call(heading: str) -> bool:
    words = re.findall(r"[a-z0-9']+", _normalise(heading).casefold())
    return " ".join(words).startswith("today's call")


def _numbers(value: Any) -> Iterator[float]:
    if isinstance(value, bool):
        return
    if isinstance(value, int | float):
        yield float(value)
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _numbers(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _numbers(item)


def _held(packet: Mapping[str, Any]) -> set[str]:
    """Every number the packet holds, as it might be quoted: whole, and to one place."""

    held: set[str] = set()
    for number in _numbers(packet):
        held.add(f"{number:.1f}")
        # A figure quoted as a whole number from a fractional reading (46.5: 46 or 47).
        held.add(str(math.floor(number)))
        held.add(str(math.ceil(number)))
    return held


def _quoted(figure: str) -> set[str]:
    value = float(figure)
    return {f"{value:.1f}", str(round(value))} if "." in figure else {str(int(value))}


def _morning_prompt_text() -> str:
    """The morning prompt's own text, for the field names it uses (imported late: the
    morning service imports this module)."""

    from src.services import morning_analysis

    return morning_analysis.SYSTEM_PROMPT


def _restates_readiness_trend(call: str, packet: Mapping[str, Any]) -> bool:
    """Does the call say the six-week readiness trend itself (Batch 377.1)?

    The app takes out a copy of its own sentence and places it after the call; a sentence
    left in the call that names readiness with six weeks, or with both of the trend's
    figures, is the brief saying it again in its own words.
    """

    trend = _mapping(_mapping(packet.get("verdict")).get("readinessBaselineTrend"))
    if not trend.get("triggered"):
        return False
    figures = {
        str(round(value))
        for value in (trend.get("usualBefore"), trend.get("usualRecent"))
        if isinstance(value, int | float) and not isinstance(value, bool)
    }
    for sentence in _SENTENCE_BREAK.split(" ".join(call.split())):
        if not _READINESS.search(sentence):
            continue
        numbers = set(re.findall(r"\d+", sentence))
        if _SIX_WEEKS.search(sentence) or (len(figures) == 2 and figures <= numbers):
            return True
    return False


def check_brief(packet: Mapping[str, Any], markdown: str) -> BriefCheck:
    """Check one written brief against the stored morning it was written from."""

    misses: list[str] = []
    sections = _sections(markdown)
    call = next((body for heading, body in sections if _is_call(heading)), None)
    if not sections or not _is_call(sections[0][0]):
        misses.append(MISS_CALL_NOT_FIRST)

    stored = _mapping(packet.get("todaysCall"))
    headline = str(stored.get("headline") or "")
    # Batch 339: "Easy riding only" shows no reading (Craig, 29 Oct), so none is required.
    reading = (
        "" if stored.get("key") == "easy_riding_only" else str(stored.get("readingWords") or "")
    )
    call_words: int | None = None
    readiness_in_call = False
    missing_openings: tuple[str, ...] = ()
    if call is not None:
        lines = [line.strip() for line in call.strip().splitlines() if line.strip()]
        opening = _normalise(re.sub(r"[*_`>]", "", lines[0])) if lines else ""
        if headline and (
            _normalise(headline) not in opening or (reading and _normalise(reading) not in opening)
        ):
            misses.append(MISS_CALL_OPENING)
        # Batch 377.1: every word under the call's heading counts, as Mark reads it there.
        call_words = len(re.findall(r"\S+", call))
        if call_words > CALL_SECTION_MAX_WORDS:
            misses.append(MISS_CALL_TOO_LONG)
        readiness_in_call = _restates_readiness_trend(call, packet)
        plain_call = _normalise(re.sub(r"\*\*|__|`", "", call))
        missing_openings = tuple(
            opening
            for opening, pattern in zip(CALL_OPENINGS, _OPENING_PATTERNS, strict=True)
            if not pattern.search(plain_call)
        )
    elif headline:
        misses.append(MISS_CALL_OPENING)

    # The stored headline may itself carry a colour ("Green light"): it is the app's own
    # signed-off words, so it is taken out before looking.
    scrubbed = _normalise(markdown)
    for words in (headline, reading):
        if words:
            scrubbed = scrubbed.replace(_normalise(words), " ")
    colours = tuple(
        sorted(
            {match.group(0) for match in _COLOUR_CASED.finditer(scrubbed)}
            | {match.group(0).lower() for match in _VERDICT.finditer(scrubbed)}
        )
    )
    if colours:
        misses.append(MISS_COLOUR_WORDS)

    held = _held(packet)
    unknown: list[str] = []
    for pattern, unit in ((_HRV, "ms"), (_BPM, "bpm"), (_SCORE, "score")):
        for match in pattern.finditer(markdown):
            figure = match.group(1)
            if not (_quoted(figure) & held):
                label = f"score {figure}" if unit == "score" else f"{figure} {unit}"
                if label not in unknown:
                    unknown.append(label)
    if unknown:
        misses.append(MISS_UNKNOWN_FIGURES)

    statistics = statistics_wording_leaks(markdown)
    if statistics:
        misses.append(MISS_STATISTICS_WORDS)
    if readiness_in_call:
        misses.append(MISS_READINESS_IN_CALL)
    engine = tuple(sorted({match.group(0).lower() for match in _ENGINE_WORDS.finditer(scrubbed)}))
    if engine:
        misses.append(MISS_ENGINE_WORDS)
    if missing_openings:
        misses.append(MISS_CALL_SHAPE)
    # Batch 382: the app's own words. Taken from the text as Mark reads it, less the stored
    # headline and reading, which are the app's own signed-off words.
    internal = internal_words(scrubbed, packet, prompt_text=_morning_prompt_text()).words
    if internal:
        misses.append(MISS_INTERNAL_WORDS)

    return BriefCheck(
        misses=tuple(misses),
        call_words=call_words,
        colour_words=colours,
        unknown_figures=tuple(unknown),
        statistics_words=statistics,
        engine_words=engine,
        missing_openings=missing_openings,
        internal_words=internal,
        details={"heading": TODAYS_CALL_HEADING},
    )
