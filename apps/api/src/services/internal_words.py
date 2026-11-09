"""The app's own words, kept out of what Mark reads (Batch 382).

Four reads Mark is waiting for used the app's internal words for what they were given:

* the 7 Nov morning brief told him "the packet only gives me today's planned sessions";
* a 3 Nov post-ride read said "that's consistent with what's in the packet";
* post-ride reads since 29 Oct (prompt v19) showed field names such as ``rideDeviation`` or
  ``upcomingWorkouts`` in 5 of 8 reads, because that prompt, unlike the morning, strength
  and review prompts, never carried ``PACKET_FIELD_NAMES_RULE`` and itself says "the
  supplied context packet";
* the 4 Nov experiment notice quoted a correlation as ``r=+0.10``.

Chat has a guard for these (``brief_chat._ANSWER_LEAKS``) that rejects the answer so it is
asked again. A stored read cannot be refused: Mark is waiting for it. So this module only
*finds* the words, in code, and the callers give a read one small repair call
(``plain_words_repair``) in the same way as the statistics words.

What counts, in written text:

* **plumbing** — the nouns in ``coach_policy.INTERNAL_VOCABULARY`` ("packet", "JSON",
  "schema", "database field", "context block", "data structure");
* **names** — a field name or an internal label: any snake_case token (no prose has one,
  and that is how a raw source label such as ``today_card_swap`` or ``operator_move``
  reads), and any camelCase token that is a key of the packet the read was written from
  or a name the prompt itself uses. Unknown camelCase is left alone on purpose:
  ``mmHg``, ``kJ`` and ``iPhone`` are camelCase and not the app's;
* **statistic symbols** — ``r=0.26`` and its spaced and signed forms.

Pure: no database, no model call.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Final

from src.services.coach_policy import INTERNAL_VOCABULARY

#: The nouns, as whole words (so "packets" counts and "unpacketed" does not).
_PLUMBING: Final = re.compile(
    r"\b(?:"
    + "|".join(re.escape(term).replace(r"\ ", r"\s+") for term in INTERNAL_VOCABULARY)
    + r")s?\b",
    re.IGNORECASE,
)
#: A camelCase or snake_case token, as written.
_CAMEL: Final = re.compile(r"\b[a-z][a-z0-9]*(?:[A-Z][A-Za-z0-9]*)+\b")
_SNAKE: Final = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
#: ``r=0.26``, ``r = -0.3``, ``r=+0.10``; not "r" in a word, not "R=" of a unit.
_STATISTIC_SYMBOL: Final = re.compile(r"(?<![A-Za-z0-9])r\s*=\s*[-+−]?\s?\d[\d.]*")


def _keys(value: Any) -> Iterator[str]:
    """Every mapping key anywhere in ``value``."""

    if isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(key, str):
                yield key
            yield from _keys(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _keys(item)


def names_in(text: str) -> frozenset[str]:
    """The camelCase and snake_case tokens a prompt or a packet uses."""

    return frozenset(_CAMEL.findall(text)) | frozenset(_SNAKE.findall(text))


def known_names(packet: Mapping[str, Any] | None, prompt_text: str = "") -> frozenset[str]:
    """The camelCase names the app uses: the packet's keys and the prompt's own tokens."""

    names = {key for key in _keys(packet or {}) if _CAMEL.fullmatch(key)}
    return frozenset(names | {name for name in names_in(prompt_text) if _CAMEL.fullmatch(name)})


@dataclass(frozen=True, slots=True)
class InternalWords:
    """What was found: each list is distinct, in the order first written."""

    plumbing: tuple[str, ...] = ()
    names: tuple[str, ...] = ()
    statistic_symbols: tuple[str, ...] = ()

    @property
    def found(self) -> bool:
        return bool(self.plumbing or self.names or self.statistic_symbols)

    @property
    def words(self) -> tuple[str, ...]:
        """Everything found, as written, to name to the repair call."""

        return (*self.plumbing, *self.names, *self.statistic_symbols)

    def to_packet(self) -> dict[str, list[str]]:
        return {
            "plumbing": list(self.plumbing),
            "names": list(self.names),
            "statisticSymbols": list(self.statistic_symbols),
        }


def _distinct(items: Iterable[str]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for item in items:
        seen.setdefault(item, None)
    return tuple(seen)


def internal_words(
    markdown: str,
    packet: Mapping[str, Any] | None = None,
    *,
    prompt_text: str = "",
    extra_names: Iterable[str] = (),
) -> InternalWords:
    """The app's own words in ``markdown`` (see the module note for what counts).

    ``packet`` and ``prompt_text`` say which camelCase tokens are the app's; ``extra_names``
    adds names a caller knows are (for example the stored headline's own words are not here:
    they hold no token of this shape).
    """

    known = known_names(packet, prompt_text) | frozenset(extra_names)
    plumbing = _distinct(match.group(0).lower() for match in _PLUMBING.finditer(markdown))
    snake = [match.group(0) for match in _SNAKE.finditer(markdown)]
    camel = [match.group(0) for match in _CAMEL.finditer(markdown) if match.group(0) in known]
    symbols = _distinct(
        match.group(0).replace(" ", "") for match in _STATISTIC_SYMBOL.finditer(markdown)
    )
    return InternalWords(
        plumbing=plumbing,
        names=_distinct([*snake, *camel]),
        statistic_symbols=symbols,
    )
