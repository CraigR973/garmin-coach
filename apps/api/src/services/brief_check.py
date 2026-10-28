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
  packet does not hold.

Pure: no database, no model call. The brief's eval (``services.brief_eval``) scores its
recorded answers with the same function.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from src.services.morning_output_contract import CALL_SECTION_MAX_WORDS, TODAYS_CALL_HEADING

MISS_CALL_NOT_FIRST: Final = "call_not_first"
MISS_CALL_OPENING: Final = "call_opening"
MISS_CALL_TOO_LONG: Final = "call_too_long"
MISS_COLOUR_WORDS: Final = "colour_words"
MISS_UNKNOWN_FIGURES: Final = "unknown_figures"
MISSES: Final = (
    MISS_CALL_NOT_FIRST,
    MISS_CALL_OPENING,
    MISS_CALL_TOO_LONG,
    MISS_COLOUR_WORDS,
    MISS_UNKNOWN_FIGURES,
)

_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(?P<heading>.+?)\s*#*\s*$", re.MULTILINE)
#: The engine's words Mark is never shown (Batch 313). Capitalised colours only: "red"
#: in running prose ("a red-letter day") is not the engine's word.
_COLOUR_CASED = re.compile(r"\b(?:Green|Amber|Red)\b")
_VERDICT = re.compile(r"\bverdicts?\b", re.IGNORECASE)
_HRV = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d+)?)\s?ms\b")
_BPM = re.compile(r"(?<![\d.])(\d{2,3}(?:\.\d+)?)\s?bpm\b", re.IGNORECASE)
_SCORE = re.compile(r"\bscore(?:\s+(?:of|was|is|at))?\s+(\d{1,3})\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class BriefCheck:
    """What the check found: the misses, and the evidence for each."""

    misses: tuple[str, ...]
    call_words: int | None = None
    colour_words: tuple[str, ...] = ()
    unknown_figures: tuple[str, ...] = ()
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


def check_brief(packet: Mapping[str, Any], markdown: str) -> BriefCheck:
    """Check one written brief against the stored morning it was written from."""

    misses: list[str] = []
    sections = _sections(markdown)
    call = next((body for heading, body in sections if _is_call(heading)), None)
    if not sections or not _is_call(sections[0][0]):
        misses.append(MISS_CALL_NOT_FIRST)

    stored = _mapping(packet.get("todaysCall"))
    headline = str(stored.get("headline") or "")
    reading = str(stored.get("readingWords") or "")
    call_words: int | None = None
    if call is not None:
        lines = [line.strip() for line in call.strip().splitlines() if line.strip()]
        opening = _normalise(re.sub(r"[*_`>]", "", lines[0])) if lines else ""
        if headline and (
            _normalise(headline) not in opening or (reading and _normalise(reading) not in opening)
        ):
            misses.append(MISS_CALL_OPENING)
        call_words = len(re.findall(r"\S+", call))
        if call_words > CALL_SECTION_MAX_WORDS:
            misses.append(MISS_CALL_TOO_LONG)
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

    return BriefCheck(
        misses=tuple(misses),
        call_words=call_words,
        colour_words=colours,
        unknown_figures=tuple(unknown),
        details={"heading": TODAYS_CALL_HEADING},
    )
