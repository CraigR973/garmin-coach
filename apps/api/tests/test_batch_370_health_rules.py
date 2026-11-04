"""Batch 370 — health rules completed.

370.1 (HS361-04, answering AI358-04): the memory filter passed 18 of 18 crafted
health-dismissing statements, so a brush-off ("chest tightness is always his asthma")
could become a standing belief of the coach's. A coaching memory is never the place for a
health attribution, and one held back goes nowhere else (Craig, 4 Nov: "Nowhere").
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pytest

from src.services.conversation_learning import (
    KIND_FACT,
    LEARNED_CONTEXT_SECTION,
    ExtractionEnvelope,
    LearningSource,
    filter_candidates,
    names_a_health_matter,
    statement_is_durable,
)

# -- 370.1: the memory filter never stores a health attribution --------------------------

#: R6's 18 health-dismissing "facts", crafted as a reader might extract them; none is his.
HEALTH_DISMISSALS = (
    "His chest tightness on climbs is always his asthma.",
    "The fluttering he feels on climbs is normal for him.",
    "Skipped beats after hard efforts are harmless for him.",
    "His left-arm ache on hard efforts is from an old shoulder injury.",
    "The jaw ache on intervals is just him clenching his teeth.",
    "Feeling light-headed after rides is fine for him.",
    "His blackout after the long ride was down to dehydration.",
    "Getting breathless on the stairs is just his fitness dropping.",
    "His heart rate jumping to 190 on easy rides is a strap glitch.",
    "His AF is managed and doesn't affect his riding.",
    "Blood pressure readings over 160 at the GP are white-coat.",
    "He takes a beta-blocker for his blood pressure.",
    "Low overnight oxygen readings are just the watch.",
    "A raised resting heart rate can be ignored when he is busy.",
    "The wheeze he gets on cold mornings is nothing.",
    "Stomach pain on hard rides is from his gels.",
    "His colds never go to his chest.",
    "A pounding heart after intervals is normal for him.",
)
#: Ways of saying the chest symptom itself that the first replay of the patterns missed.
CHEST_SAID_PLAINLY = (
    "His chest gets tight on long climbs.",
    "A tight chest on cold mornings is normal for him.",
)
#: R6's 7 ordinary statements: "heart" and "chest" are everyday training words.
TRAINING_FACTS = (
    "He trains with a chest-strap heart-rate monitor.",
    "His heart rate drifts up a few beats in a warm room.",
    "His Zone 2 sits at about 120 bpm.",
    "He gets breathless on VO2 intervals, which he expects.",
    "He prefers heart-rate targets to power on easy rides.",
    "His resting heart rate is usually in the mid-40s.",
    "He likes the coach to explain his heart-rate zones.",
)


@pytest.mark.parametrize("statement", HEALTH_DISMISSALS)
def test_a_health_attribution_is_never_a_memory(statement: str) -> None:
    assert names_a_health_matter(statement)
    assert not statement_is_durable(statement, kind=KIND_FACT)


@pytest.mark.parametrize("statement", CHEST_SAID_PLAINLY)
def test_the_chest_symptom_said_plainly_is_caught(statement: str) -> None:
    assert names_a_health_matter(statement)


@pytest.mark.parametrize("statement", TRAINING_FACTS)
def test_his_training_facts_still_pass(statement: str) -> None:
    assert not names_a_health_matter(statement)
    assert statement_is_durable(statement, kind=KIND_FACT)


@pytest.mark.parametrize(
    "statement",
    (
        "He races best in April.",
        "He sleeps with blackout blinds.",
        "He uses a medicine ball for core work.",
        "His power collapses after two hours without food.",
        "He calls threshold work the hurt locker.",
    ),
)
def test_words_that_only_look_medical_pass(statement: str) -> None:
    assert not names_a_health_matter(statement)


def _source(text: str) -> LearningSource:
    return LearningSource(
        source_id="chat:1",
        source_type="chat",
        source_date=date(2026, 11, 4),
        text=text,
        occurred_at_utc=datetime(2026, 11, 4, 9, 0),
    )


def _kept(statement: str, quotes: list[str], said: str) -> list[Any]:
    candidate = {
        "kind": KIND_FACT,
        "statement": statement,
        "destination": LEARNED_CONTEXT_SECTION,
        "experiment": None,
        "evidence": [{"source_id": "chat:1", "quote": quote} for quote in quotes],
    }
    return filter_candidates(
        ExtractionEnvelope.model_validate({"candidates": [candidate]}),
        sources=[_source(said)],
        existing_statements=[],
    )


def test_nor_a_memory_whose_evidence_is_his_words_about_his_health() -> None:
    """A tidy statement drawn partly from a health quote would still store the quote."""

    said = "Long climbs feel hard lately, and my chest gets tight on the long climbs."
    statement = "Long climbs feel hard to him lately."
    assert _kept(statement, ["Long climbs feel hard lately"], said)
    assert not _kept(
        statement, ["Long climbs feel hard lately", "my chest gets tight on the long climbs"], said
    )
